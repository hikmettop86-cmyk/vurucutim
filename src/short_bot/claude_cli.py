"""Wrapper around `claude` CLI in headless (-p) mode. JSON-only output."""
from __future__ import annotations

import json
import re
import subprocess
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class ClaudeCliError(RuntimeError):
    pass


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)
_FIRST_OBJ_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


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
    retries: int = 2,
    timeout_s: int = 180,
) -> T:
    """Invoke `claude -p PROMPT --output-format text` and parse output as JSON validating against `schema`.

    Args:
        prompt: prompt text passed to claude via -p
        schema: Pydantic BaseModel subclass to validate the parsed JSON against
        claude_path: path to claude CLI binary (default 'claude' resolves via PATH)
        retries: total number of attempts (NOT retries-after-first); minimum useful value is 1
        timeout_s: per-attempt subprocess timeout in seconds

    Raises:
        ClaudeCliError: if all attempts fail (parse error, validation error, exit != 0, timeout)
                        or immediately if claude binary is not found
    """
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            proc = subprocess.run(
                [claude_path, "-p", prompt, "--output-format", "text"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_s,
                check=False,
            )
        except FileNotFoundError as e:
            # Don't retry — sleeping won't make the binary appear
            raise ClaudeCliError(
                f"claude binary not found at {claude_path!r}. "
                f"Install Claude Code CLI or set claude_cli_path in config/settings.yaml."
            ) from e
        except subprocess.TimeoutExpired as e:
            last_error = e
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

        if proc.returncode != 0:
            last_error = ClaudeCliError(f"claude exit {proc.returncode}: {proc.stderr[:500]}")
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

        try:
            payload = _extract_json(proc.stdout)
            data = json.loads(payload)
            return schema.model_validate(data)
        except (ValueError, json.JSONDecodeError, ValidationError) as e:
            last_error = e
            if attempt < retries:
                time.sleep(2 ** attempt)
            continue

    raise ClaudeCliError(f"claude_cli failed after {retries} attempts: {last_error}")
