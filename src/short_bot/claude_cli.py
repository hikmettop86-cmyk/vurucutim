"""Wrapper around `claude` CLI in headless (-p) mode. JSON-only output."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class AIBackendError(RuntimeError):
    """AI motorlarının ortak hata tabanı (Claude CLI + OpenRouter)."""
    pass


class ClaudeCliError(AIBackendError):
    pass


class OpenRouterError(AIBackendError):
    pass


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)
_FIRST_OBJ_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def _resolve_claude_binary(claude_path: str) -> str:
    """Resolve a bare 'claude' to an absolute path so subprocess.run on Windows
    can find npm `.cmd` shims (CreateProcess in shell=False mode does NOT honor
    PATHEXT for non-.exe shims unless given the full path).

    Strategy:
      1. If user already gave an absolute or qualified path → trust it as-is.
      2. shutil.which('claude') → respects PATHEXT, finds claude.cmd / .exe.
      3. Probe well-known npm-global / Anthropic install locations.
      4. Give up and return original; subprocess will raise FileNotFoundError
         which the caller turns into a ClaudeCliError with install hint.
    """
    if claude_path != "claude":
        return claude_path

    found = shutil.which("claude")
    if found:
        return found

    candidates = [
        os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd"),
        os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.exe"),
        os.path.join(os.environ.get("USERPROFILE", ""), ".local", "bin", "claude.exe"),
        os.path.join(os.environ.get("USERPROFILE", ""), ".local", "bin", "claude.cmd"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "claude", "claude.exe"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c

    return claude_path


def _extract_json(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise ValueError("empty output")
    m = _CODE_FENCE_RE.search(raw)
    if m:
        return m.group(1)
    m = _FIRST_OBJ_RE.search(raw)
    if m:
        return m.group(1)
    return raw


def _invoke_raw(prompt: str, *, backend: str, model: str,
                claude_path: str, api_key: str | None, timeout_s: int) -> str:
    """Tek-atış ham çıktı. claude_cli → subprocess; openrouter → HTTP.
    FileNotFoundError ve TimeoutExpired'i (claude_cli) yukarıya bırakır;
    diğer hatalarda ClaudeCliError/OpenRouterError fırlatır."""
    if backend == "openrouter":
        from short_bot import openrouter_client   # fonksiyon-içi import → circular önler
        return openrouter_client.complete(prompt, model=model,
                                          api_key=api_key, timeout_s=timeout_s)
    resolved_path = _resolve_claude_binary(claude_path)
    cmd = [resolved_path, "-p", "--output-format", "text"]
    if model != "default":
        cmd += ["--model", model]
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                          encoding="utf-8", timeout=timeout_s, check=False)
    if proc.returncode != 0:
        raise ClaudeCliError(f"claude exit {proc.returncode}: {proc.stderr[:500]}")
    return proc.stdout


def run_json(
    prompt: str,
    schema: type[T],
    *,
    claude_path: str = "claude",
    model: str = "default",
    backend: str = "claude_cli",
    api_key: str | None = None,
    retries: int = 2,
    timeout_s: int = 180,
) -> T:
    """Prompt'u backend'e gönder, çıktıyı JSON olarak parse edip schema ile doğrula.

    backend: "claude_cli" (varsayılan, `claude -p`) | "openrouter" (HTTP).
    api_key: yalnızca backend="openrouter" için gerekli.
    """
    last_error: Exception | None = None
    retry_feedback: str = ""

    for attempt in range(1, retries + 1):
        current_prompt = prompt + retry_feedback if retry_feedback else prompt
        try:
            raw = _invoke_raw(current_prompt, backend=backend, model=model,
                              claude_path=claude_path, api_key=api_key,
                              timeout_s=timeout_s)
        except FileNotFoundError as e:
            raise ClaudeCliError(
                f"claude binary not found at {claude_path!r}. "
                f"Install Claude Code CLI or set claude_cli_path in config/settings.yaml."
            ) from e
        except (subprocess.TimeoutExpired, AIBackendError) as e:
            last_error = e
            retry_feedback = ""
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

        try:
            payload = _extract_json(raw)
            data = json.loads(payload)
            return schema.model_validate(data)
        except (ValueError, json.JSONDecodeError, ValidationError) as e:
            last_error = e
            retry_feedback = (
                "\n\n---\nPREVIOUS ATTEMPT WAS REJECTED WITH ERROR:\n"
                f"{e}\n"
                "Please fix this error and return ONLY valid JSON, no other text."
            )
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

    err_cls = OpenRouterError if backend == "openrouter" else ClaudeCliError
    raise err_cls(f"run_json failed after {retries} attempts: {last_error}")
