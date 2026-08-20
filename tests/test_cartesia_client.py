"""short_bot.tts.cartesia_client — SSE sentez, sesler, sağlık, klon, kredi sayacı."""
from __future__ import annotations

import json
import wave
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from short_bot.tts import cartesia_client as cc

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def sse_text() -> str:
    return (FIX / "cartesia_sse_tr.txt").read_text(encoding="utf-8")


class _Resp:
    def __init__(self, text="", status=200, payload=None):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("json yok")
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


# --- parse_sse ----------------------------------------------------------------------

def test_parse_sse_fixture(sse_text):
    pcm, words = cc.parse_sse(sse_text)
    assert len(pcm) == 275184
    assert [w.word for w in words] == ["Adalar", "yine", "sallandı.", "Kandilli", "üç", "nokta", "bir", "dedi."]
    assert words[0].start_s < words[0].end_s <= words[1].start_s + 0.01
    assert words[-1].end_s == pytest.approx(3.0)


def test_parse_sse_ignores_garbage_lines():
    pcm, words = cc.parse_sse("event: x\ndata: {not json}\ndata: {\"type\":\"done\"}\n")
    assert pcm == b"" and words == []


# --- synthesize ---------------------------------------------------------------------

def test_synthesize_writes_wav_and_words(tmp_path, sse_text):
    sess = _Session([_Resp(sse_text)])
    res = cc.synthesize("Adalar yine sallandı. Kandilli üç nokta bir dedi.",
                        voice_id="v1", api_key="k", out_path=tmp_path / "narration.mp3",
                        language="tr", session=sess, usage_dir=tmp_path)
    assert res.path == tmp_path / "narration.wav" and res.path.exists()
    with wave.open(str(res.path)) as w:
        assert w.getframerate() == 44100 and w.getnchannels() == 1 and w.getsampwidth() == 2
        assert w.getnframes() == 275184 // 2
    assert res.duration_s == pytest.approx(3.12, abs=0.01)
    assert res.words[0].word == "Adalar" and len(res.words) == 8
    assert res.chars_spent == len("Adalar yine sallandı. Kandilli üç nokta bir dedi.")
    assert cc.month_usage(tmp_path) == res.chars_spent
    body = sess.calls[0][2]["json"]
    assert body["model_id"] == "sonic-3.5"
    assert body["language"] == "tr"
    assert body["voice"] == {"mode": "id", "id": "v1"}
    assert body["add_timestamps"] is True
    assert body["output_format"] == {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 44100}
    assert sess.calls[0][2]["headers"]["Cartesia-Version"] == cc.VERSION


def test_synthesize_clamps_speed_and_volume(tmp_path, sse_text, caplog):
    sess = _Session([_Resp(sse_text)])
    with caplog.at_level("WARNING"):
        cc.synthesize("metin", voice_id="v", api_key="k", out_path=tmp_path / "a.wav",
                      speed=0.5, volume=3.0, session=sess)
    gc = sess.calls[0][2]["json"]["generation_config"]
    assert gc == {"speed": 0.6, "volume": 2.0}
    assert "hız 0.5 → 0.6" in caplog.text and "ses seviyesi 3.0 → 2.0" in caplog.text


def test_synthesize_passes_model_and_emotion(tmp_path, sse_text):
    sess = _Session([_Resp(sse_text)])
    cc.synthesize("metin", voice_id="v", api_key="k", out_path=tmp_path / "a.wav",
                  model="sonic-preview", emotion="[sakin, güven veren]", session=sess)
    body = sess.calls[0][2]["json"]
    assert body["model_id"] == "sonic-preview"
    assert body["transcript"].startswith("[sakin, güven veren] metin")


def test_synthesize_rejects_tiny_audio(tmp_path):
    sess = _Session([_Resp('data: {"type":"done","done":true}\n')])
    with pytest.raises(cc.CartesiaError, match="çok küçük"):
        cc.synthesize("metin", voice_id="v", api_key="k", out_path=tmp_path / "a.wav", session=sess)


def test_synthesize_retries_on_429_then_succeeds(tmp_path, sse_text):
    sess = _Session([_Resp("slow down", 429), _Resp(sse_text)])
    slept = []
    res = cc.synthesize("metin", voice_id="v", api_key="k", out_path=tmp_path / "a.wav",
                        session=sess, sleep=slept.append)
    assert res.path.exists() and slept == [2.0]


def test_synthesize_gives_up_after_retries(tmp_path):
    sess = _Session([_Resp("x", 429)] * 4)
    with pytest.raises(cc.CartesiaRateLimitError):
        cc.synthesize("metin", voice_id="v", api_key="k", out_path=tmp_path / "a.wav",
                      session=sess, sleep=lambda s: None)


def test_synthesize_auth_error_is_not_retried(tmp_path):
    sess = _Session([_Resp("nope", 401)])
    with pytest.raises(cc.CartesiaAuthError):
        cc.synthesize("metin", voice_id="v", api_key="k", out_path=tmp_path / "a.wav", session=sess)
    assert len(sess.calls) == 1


def test_synthesize_requires_key_and_voice(tmp_path):
    with pytest.raises(cc.CartesiaAuthError):
        cc.synthesize("m", voice_id="v", api_key="", out_path=tmp_path / "a.wav")
    with pytest.raises(cc.CartesiaError):
        cc.synthesize("m", voice_id="", api_key="k", out_path=tmp_path / "a.wav")


def test_split_text_prefers_sentence_boundaries():
    text = ("Birinci cümle burada. " * 100).strip()
    parts = cc._split_text(text, limit=500)
    assert all(len(p) <= 500 for p in parts)
    assert all(p.endswith(".") for p in parts[:-1])
    assert " ".join(parts) == text


def test_synthesize_offsets_words_across_chunks(tmp_path, sse_text, monkeypatch):
    monkeypatch.setattr(cc, "CHUNK_CHARS", 30)
    sess = _Session([_Resp(sse_text), _Resp(sse_text)])
    res = cc.synthesize("Adalar yine sallandı. Kandilli üç nokta bir dedi.",
                        voice_id="v", api_key="k", out_path=tmp_path / "a.wav", session=sess)
    assert len(sess.calls) == 2 and len(res.words) == 16
    assert res.words[8].start_s == pytest.approx(res.words[0].start_s + 3.12, abs=0.01)
    assert res.duration_s == pytest.approx(6.24, abs=0.02)


# --- health -------------------------------------------------------------------------

def test_health_check_states(tmp_path, sse_text):
    assert cc.health_check(voice_id="v", api_key="") == "no-key"
    assert cc.health_check(voice_id="", api_key="k") == "no-voice"
    assert cc.health_check(voice_id="v", api_key="k", session=_Session([_Resp("", 401)])) == "auth"
    assert cc.health_check(voice_id="v", api_key="k", session=_Session([_Resp("", 404)])) == "voice-missing"
    assert cc.health_check(voice_id="v", api_key="k", probe_model=False,
                           session=_Session([_Resp("", 200)])) == "healthy"
    ok = _Session([_Resp("", 200), _Resp(sse_text)])
    assert cc.health_check(voice_id="v", api_key="k", session=ok, tmp_dir=tmp_path) == "healthy"
    bad_model = _Session([_Resp("", 200), _Resp('{"message":"model_not_found"}', 404)])
    assert cc.health_check(voice_id="v", api_key="k", session=bad_model, tmp_dir=tmp_path) == "model"
    assert set(cc.HEALTH_MESSAGES_TR) >= {"healthy", "no-key", "no-voice", "auth", "voice-missing", "model", "error"}


# --- voices / models / clone ------------------------------------------------------

def test_list_voices_maps_fields_and_filters_language():
    payload = {"data": [{"id": "a", "name": "Taylan", "language": "tr", "gender": "masculine",
                         "is_pro": False, "is_owner": False, "preview_file_url": "https://p/a.wav",
                         "description": "Versatile"},
                        {"id": "b", "name": "Pro", "is_pro": True, "is_owner": True}]}
    sess = _Session([_Resp("", 200, payload)])
    out = cc.list_voices(api_key="k", language="tr", session=sess)
    assert out[0] == {"voice_id": "a", "name": "Taylan", "description": "Versatile", "language": "tr",
                      "gender": "masculine", "is_owner": False, "is_pro": False,
                      "preview_url": "https://p/a.wav"}
    assert out[1]["is_pro"] is True and out[1]["is_owner"] is True
    params = dict(sess.calls[0][2]["params"])
    assert params["language"] == "tr" and params["expand[]"] == "preview_file_url"


def test_list_voices_errors_return_empty():
    assert cc.list_voices(api_key="", language="tr") == []
    assert cc.list_voices(api_key="k", session=_Session([_Resp("boom", 500)])) == []
    assert cc.list_voices(api_key="k", session=_Session([requests.ConnectionError("x")])) == []


def test_probe_models_classifies(sse_text):
    sess = _Session([_Resp(sse_text), _Resp('{"message":"model_sunsetted"}', 400),
                     _Resp('{"message":"voice not found"}', 404)])
    out = cc.probe_models(api_key="k", candidates=("a", "b", "c"), session=sess)
    assert [(o["id"], o["ok"], o["reason"]) for o in out] == [("a", True, ""), ("b", False, "emekli"), ("c", True, "")]


def test_clone_voice_trims_long_clip(tmp_path, monkeypatch):
    clip = tmp_path / "ref.mp3"
    clip.write_bytes(b"x" * 2048)
    monkeypatch.setattr(cc, "_probe_seconds", lambda p, f: 23.0)
    ran = {}

    def _fake_run(cmd, **kw):
        ran["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"y" * 2048)
        return None
    monkeypatch.setattr(cc.subprocess, "run", _fake_run)
    sess = _Session([_Resp("", 200, {"id": "new-voice"})])
    vid, trimmed = cc.clone_voice(api_key="k", name="Ben", clip_path=clip, language="tr", session=sess)
    assert vid == "new-voice" and trimmed is True
    assert "-ss" in ran["cmd"] and "-t" in ran["cmd"]
    assert sess.calls[0][2]["data"]["language"] == "tr"
    assert not list(tmp_path.glob(".cartesia-klip-*"))


def test_clone_voice_rejects_bad_extension(tmp_path):
    clip = tmp_path / "ref.txt"
    clip.write_text("x")
    with pytest.raises(cc.CartesiaError, match="uzantı"):
        cc.clone_voice(api_key="k", name="n", clip_path=clip, language="tr")


# --- usage --------------------------------------------------------------------------

def test_usage_counter_is_monthly(tmp_path):
    jan = datetime(2026, 1, 5, tzinfo=timezone.utc)
    feb = datetime(2026, 2, 5, tzinfo=timezone.utc)
    assert cc.record_usage(100, cache_dir=tmp_path, now=jan) == 100
    assert cc.record_usage(50, cache_dir=tmp_path, now=jan) == 150
    assert cc.record_usage(7, cache_dir=tmp_path, now=feb) == 7
    assert cc.month_usage(tmp_path, now=jan) == 150
    assert cc.month_usage(tmp_path, now=feb) == 7
    (tmp_path / "cartesia_usage.json").write_text("{bozuk", encoding="utf-8")
    assert cc.month_usage(tmp_path, now=jan) == 0
    assert cc.record_usage(1, cache_dir=tmp_path, now=jan) == 1


def test_resolve_key_prefers_secrets(monkeypatch):
    monkeypatch.setenv("CARTESIA_API_KEY", "env-key")
    assert cc.resolve_cartesia_api_key({"cartesia_api_key": "s"}) == "s"
    assert cc.resolve_cartesia_api_key({}) == "env-key"
    monkeypatch.delenv("CARTESIA_API_KEY")
    assert cc.resolve_cartesia_api_key(None) == ""
