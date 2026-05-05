import json
from unittest.mock import patch, MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from short_bot.claude_cli import run_json, ClaudeCliError


class _Out(BaseModel):
    score: float
    why: str


def _fake_proc(stdout: str, returncode: int = 0):
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = ""
    return p


def test_run_json_parses_valid(tmp_path):
    payload = {"score": 8.5, "why": "interesting"}
    with patch("short_bot.claude_cli.subprocess.run",
               return_value=_fake_proc(json.dumps(payload))):
        result = run_json("prompt", _Out, claude_path="claude")
    assert result.score == 8.5


def test_run_json_extracts_from_code_fence():
    text = "Here you go:\n```json\n{\"score\": 7.2, \"why\": \"ok\"}\n```\nDone."
    with patch("short_bot.claude_cli.subprocess.run",
               return_value=_fake_proc(text)):
        r = run_json("p", _Out, claude_path="claude")
    assert r.score == 7.2


def test_run_json_retries_on_invalid():
    bad = "not json at all"
    good = json.dumps({"score": 6.0, "why": "x"})
    with patch("short_bot.claude_cli.subprocess.run",
               side_effect=[_fake_proc(bad), _fake_proc(good)]):
        r = run_json("p", _Out, claude_path="claude", retries=2)
    assert r.score == 6.0


def test_run_json_raises_after_retries_exhausted():
    bad = "not json"
    with patch("short_bot.claude_cli.subprocess.run",
               return_value=_fake_proc(bad)):
        with pytest.raises(ClaudeCliError):
            run_json("p", _Out, claude_path="claude", retries=2)


def test_run_json_raises_on_non_zero_exit():
    with patch("short_bot.claude_cli.subprocess.run",
               return_value=_fake_proc("", returncode=1)):
        with pytest.raises(ClaudeCliError):
            run_json("p", _Out, claude_path="claude", retries=1)
