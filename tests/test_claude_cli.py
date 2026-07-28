import json
from unittest.mock import patch, MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from short_bot.claude_cli import run_json, ClaudeCliError, _resolve_claude_binary


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


def test_resolve_passes_through_qualified_path():
    """Already-qualified paths must be trusted — never overridden by which()."""
    assert _resolve_claude_binary(r"C:\custom\claude.exe") == r"C:\custom\claude.exe"


def test_resolve_uses_shutil_which_for_bare_claude():
    with patch("short_bot.claude_cli.shutil.which", return_value=r"C:\Users\X\AppData\Roaming\npm\claude.cmd"):
        assert _resolve_claude_binary("claude") == r"C:\Users\X\AppData\Roaming\npm\claude.cmd"


def test_resolve_falls_back_to_known_npm_dir(monkeypatch):
    """When PATH lookup fails, probe %APPDATA%\\npm\\claude.cmd."""
    monkeypatch.setenv("APPDATA", r"C:\Users\X\AppData\Roaming")
    expected = r"C:\Users\X\AppData\Roaming\npm\claude.cmd"
    with patch("short_bot.claude_cli.shutil.which", return_value=None), \
         patch("short_bot.claude_cli.os.path.isfile", side_effect=lambda p: p == expected):
        assert _resolve_claude_binary("claude") == expected


def test_resolve_returns_original_when_nothing_found():
    """Caller will see FileNotFoundError → ClaudeCliError with install hint."""
    with patch("short_bot.claude_cli.shutil.which", return_value=None), \
         patch("short_bot.claude_cli.os.path.isfile", return_value=False):
        assert _resolve_claude_binary("claude") == "claude"


def test_run_json_uses_resolved_path_in_subprocess():
    """run_json must invoke subprocess with the resolved path, not the bare 'claude'."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _fake_proc(json.dumps({"score": 5.0, "why": "x"}))

    with patch("short_bot.claude_cli._resolve_claude_binary", return_value=r"C:\fake\claude.cmd"), \
         patch("short_bot.claude_cli.subprocess.run", side_effect=fake_run):
        run_json("p", _Out, claude_path="claude", retries=1)
    assert captured["cmd"][0] == r"C:\fake\claude.cmd"


def test_error_hierarchy():
    from short_bot.claude_cli import AIBackendError, ClaudeCliError, OpenRouterError
    assert issubclass(ClaudeCliError, AIBackendError)
    assert issubclass(OpenRouterError, AIBackendError)
    # Eski kod `except ClaudeCliError` ile yakalamaya devam etmeli
    assert issubclass(ClaudeCliError, RuntimeError)


def test_run_json_openrouter_backend_parses(tmp_path):
    payload = json.dumps({"score": 8.0, "why": "ok"})
    with patch("short_bot.openrouter_client.complete", return_value=payload) as p:
        result = run_json("prompt", _Out, backend="openrouter",
                          model="anthropic/claude-opus-4.8", api_key="k")
    assert result.score == 8.0
    assert p.call_args.kwargs["model"] == "anthropic/claude-opus-4.8"
    assert p.call_args.kwargs["api_key"] == "k"


def test_run_json_openrouter_retries_on_invalid():
    bad, good = "not json", json.dumps({"score": 6.0, "why": "x"})
    with patch("short_bot.openrouter_client.complete", side_effect=[bad, good]), \
         patch("short_bot.claude_cli.time.sleep"):
        r = run_json("p", _Out, backend="openrouter", model="m", api_key="k", retries=2)
    assert r.score == 6.0


def test_run_json_default_backend_is_claude_cli():
    with patch("short_bot.claude_cli.subprocess.run",
               return_value=_fake_proc(json.dumps({"score": 5.0, "why": "x"}))) as sp:
        run_json("p", _Out, claude_path="claude")
    assert sp.called  # subprocess çağrıldı = claude_cli yolu


def test_run_json_openrouter_failure_raises_openrouter_error():
    """openrouter backend'inde tum denemeler basarisiz olursa OpenRouterError firlar (ClaudeCliError degil)."""
    from short_bot.claude_cli import OpenRouterError
    with patch("short_bot.openrouter_client.complete",
               side_effect=OpenRouterError("key yok")), \
         patch("short_bot.claude_cli.time.sleep"):
        with pytest.raises(OpenRouterError):
            run_json("p", _Out, backend="openrouter", model="m", api_key=None, retries=2)


def test_run_json_claude_cli_failure_still_raises_claude_cli_error():
    """claude_cli backend'inde davranis degismez: ClaudeCliError firlar."""
    with patch("short_bot.claude_cli.subprocess.run",
               return_value=_fake_proc("not json")), \
         patch("short_bot.claude_cli.time.sleep"):
        with pytest.raises(ClaudeCliError):
            run_json("p", _Out, claude_path="claude", retries=2)


def test_run_json_openrouter_forwards_image_path(tmp_path):
    img = tmp_path / "x.jpg"
    img.write_bytes(b"jpeg")
    payload = json.dumps({"score": 1.0, "why": "ok"})
    with patch("short_bot.openrouter_client.complete", return_value=payload) as p:
        run_json("p", _Out, backend="openrouter", model="g", api_key="k", image_path=img)
    assert p.call_args.kwargs["image_path"] == img


def test_run_json_claude_cli_prepends_image_path(tmp_path):
    img = tmp_path / "x.jpg"
    img.write_bytes(b"jpeg")
    captured = {}
    def fake_run(cmd, **kwargs):
        captured["input"] = kwargs.get("input", "")
        return _fake_proc(json.dumps({"score": 1.0, "why": "ok"}))
    with patch("short_bot.claude_cli.subprocess.run", side_effect=fake_run):
        run_json("PROMPT", _Out, claude_path="claude", image_path=img, retries=1)
    assert captured["input"].startswith("@")
    assert "PROMPT" in captured["input"]


def test_attachable_image_always_fits_large_noisy_image(tmp_path):
    """GÖRSEL SINIRA İNDİRİLEMEYİNCE ADAY KÖR SKORLANIYOR (gerçek koşu 1327/1314).

    Log: 'cevher[merak]: skor hatası (görsel 262144 bayt sınırına indirilemedi →
    gönderilmiyor) → nötr 5'. Yani kapak görseli küçültülemeyince aday YARGISIZ kalıp
    sabit 5 puan alıyor — merak sıralaması o adaylar için anlamsızlaşıyor, zayıf klip
    güçlünün önüne geçebiliyor.

    KÖK: kalite/ölçek merdiveni (70/1.0, 55/1.0, 45/0.8, 35/0.65) en agresif adımda bile
    büyük/gürültülü bir görseli sınıra indiremiyor. Merdiven hedefe ULAŞANA KADAR
    inmeli — 256KB'a sığmayan bir kapak pratikte yok."""
    import numpy as np
    from PIL import Image

    from short_bot.claude_cli import CLI_IMAGE_MAX_BYTES, _attachable_image

    # gürültü = JPEG'in sıkıştıramadığı en kötü durum
    rng = np.random.default_rng(7)
    arr = rng.integers(0, 256, size=(2400, 2400, 3), dtype=np.uint8)
    big = tmp_path / "noisy.png"
    Image.fromarray(arr).save(big, "PNG")
    assert big.stat().st_size > CLI_IMAGE_MAX_BYTES * 4

    with _attachable_image(big) as fitted:
        assert fitted.stat().st_size <= CLI_IMAGE_MAX_BYTES, (
            f"görsel sınıra indirilemedi ({fitted.stat().st_size} bayt) → aday kör skorlanır")


def test_attachable_image_leaves_small_file_untouched(tmp_path):
    """Bütçe altındaki görsele DOKUNULMAZ (gereksiz yeniden kodlama yok)."""
    from PIL import Image

    from short_bot.claude_cli import _attachable_image

    small = tmp_path / "small.jpg"
    Image.new("RGB", (64, 64), "white").save(small, "JPEG")
    with _attachable_image(small) as p:
        assert p == small
