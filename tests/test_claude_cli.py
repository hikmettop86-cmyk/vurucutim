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


def test_run_json_raises_immediately_on_missing_binary():
    with patch("short_bot.claude_cli.subprocess.run", side_effect=FileNotFoundError("not found")):
        with pytest.raises(ClaudeCliError, match="not found"):
            run_json("p", _Out, claude_path="claude_missing", retries=3)


def test_run_json_retries_on_timeout_then_succeeds():
    import subprocess as _sp
    good = json.dumps({"score": 5.0, "why": "ok"})
    with patch("short_bot.claude_cli.subprocess.run",
               side_effect=[_sp.TimeoutExpired(cmd="claude", timeout=1), _fake_proc(good)]), \
         patch("short_bot.claude_cli.time.sleep"):  # don't actually sleep
        r = run_json("p", _Out, claude_path="claude", retries=2)
    assert r.score == 5.0


def test_run_json_passes_model_flag():
    payload = {"score": 7.0, "why": "ok"}
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _fake_proc(json.dumps(payload))

    with patch("short_bot.claude_cli.subprocess.run", side_effect=fake_run):
        run_json("p", _Out, claude_path="claude", model="opus", retries=1)
    assert "--model" in captured["cmd"]
    assert "opus" in captured["cmd"]


def test_run_json_retry_includes_validation_error_feedback():
    """When validation fails, the retry prompt must include the error so Claude can fix it."""
    bad = json.dumps({"score": "not_a_number", "why": "x"})
    good = json.dumps({"score": 6.0, "why": "x"})
    captured_inputs: list[str] = []

    def fake_run(cmd, **kwargs):
        captured_inputs.append(kwargs.get("input", ""))
        return _fake_proc(bad if len(captured_inputs) == 1 else good)

    with patch("short_bot.claude_cli.subprocess.run", side_effect=fake_run), \
         patch("short_bot.claude_cli.time.sleep"):
        r = run_json("ORIGINAL_PROMPT", _Out, claude_path="claude", retries=2)
    assert r.score == 6.0
    assert captured_inputs[0] == "ORIGINAL_PROMPT"
    assert "ORIGINAL_PROMPT" in captured_inputs[1]
    assert "PREVIOUS ATTEMPT WAS REJECTED" in captured_inputs[1]
    assert "score" in captured_inputs[1]


def test_run_json_default_model_omits_flag():
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _fake_proc(json.dumps({"score": 5, "why": "x"}))

    with patch("short_bot.claude_cli.subprocess.run", side_effect=fake_run):
        run_json("p", _Out, claude_path="claude", model="default", retries=1)
    assert "--model" not in captured["cmd"]
