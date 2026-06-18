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


def run_json(
    prompt: str,
    schema: type[T],
    *,
    claude_path: str = "claude",
    model: str = "default",
    retries: int = 2,
    timeout_s: int = 180,
) -> T:
    """Invoke `claude -p PROMPT --output-format text` and parse output as JSON validating against `schema`.

    Args:
        prompt: prompt text passed to claude via -p
        schema: Pydantic BaseModel subclass to validate the parsed JSON against
        claude_path: path to claude CLI binary (default 'claude' resolves via PATH)
        model: Claude model to use (e.g. 'opus', 'sonnet', 'haiku'); default 'default' omits the --model flag
        retries: total number of attempts (NOT retries-after-first); minimum useful value is 1
        timeout_s: per-attempt subprocess timeout in seconds

    Raises:
        ClaudeCliError: if all attempts fail (parse error, validation error, exit != 0, timeout)
                        or immediately if claude binary is not found
    """
    last_error: Exception | None = None
    retry_feedback: str = ""

    resolved_path = _resolve_claude_binary(claude_path)

    for attempt in range(1, retries + 1):
        current_prompt = prompt + retry_feedback if retry_feedback else prompt
        try:
            # Pass prompt via stdin (not argv) — Windows argv encoding mangles
            # non-ASCII characters silently, causing Sonnet to receive a
            # corrupted prompt and return empty output.
            cmd = [resolved_path, "-p", "--output-format", "text"]
            if model != "default":
                cmd += ["--model", model]
            proc = subprocess.run(
                cmd,
                input=current_prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_s,
                check=False,
            )
        except FileNotFoundError as e:
            # Don't retry — sleeping won't make the binary appear
            raise ClaudeCliError(
                f"claude binary not found at {claude_path!r} "
                f"(resolved to {resolved_path!r}). "
                f"Install Claude Code CLI or set claude_cli_path in config/settings.yaml."
            ) from e
        except subprocess.TimeoutExpired as e:
            last_error = e
            retry_feedback = ""
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

        if proc.returncode != 0:
            last_error = ClaudeCliError(f"claude exit {proc.returncode}: {proc.stderr[:500]}")
            retry_feedback = ""
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

        try:
            payload = _extract_json(proc.stdout)
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

    raise ClaudeCliError(f"claude_cli failed after {retries} attempts: {last_error}")
