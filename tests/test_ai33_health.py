from short_bot.tts.ai33_client import (Ai33Error, Ai33TimeoutError,
                                       health_check, list_voices)
from tests.test_ai33_synthesize import FakeResponse, FakeSession, _clock


def test_health_check_healthy(tmp_path):
    sess = FakeSession(
        post_resp=FakeResponse(200, {"task_id": "t1"}),
        task_resps=[FakeResponse(200, {"status": "done",
                                       "metadata": {"audio_url": "https://cdn/a.mp3"}})],
        audio_resp=FakeResponse(200, content=b"mp3"),
    )
    assert health_check(voice_id="v", api_key="k", tmp_dir=tmp_path,
                        session=sess, sleep=lambda s: None, now=_clock()) == "healthy"


def test_health_check_no_key(tmp_path):
    assert health_check(voice_id="v", api_key="", tmp_dir=tmp_path) == "no-key"


def test_health_check_no_voice(tmp_path):
    assert health_check(voice_id="", api_key="k", tmp_dir=tmp_path) == "no-voice"


def test_health_check_auth(tmp_path):
    sess = FakeSession(post_resp=FakeResponse(401, {}), task_resps=[])
    assert health_check(voice_id="v", api_key="bad", tmp_dir=tmp_path,
                        session=sess, sleep=lambda s: None, now=_clock()) == "auth"


def test_health_check_stalled_on_timeout(tmp_path):
    """Kuyruk 'doing'de takiliysa -> stalled (asla exception atmaz)."""
    sess = FakeSession(
        post_resp=FakeResponse(200, {"task_id": "t1"}),
        task_resps=[FakeResponse(200, {"status": "doing"})] * 50,
    )
    assert health_check(voice_id="v", api_key="k", tmp_dir=tmp_path,
                        session=sess, sleep=lambda s: None, now=_clock(),
                        timeout_s=3.0) == "stalled"


def test_health_check_error_on_task_failure(tmp_path):
    sess = FakeSession(
        post_resp=FakeResponse(200, {"task_id": "t1"}),
        task_resps=[FakeResponse(200, {"status": "error", "error_message": "bozuk"})],
    )
    assert health_check(voice_id="v", api_key="k", tmp_dir=tmp_path,
                        session=sess, sleep=lambda s: None, now=_clock()) == "error"


def test_list_voices_returns_items():
    sess = FakeSession(post_resp=None, task_resps=[],
                       audio_resp=FakeResponse(200, {"data": [
                           {"voice_id": "elevenlabs_a", "name": "Ada"},
                       ]}))
    voices = list_voices(api_key="k", session=sess)
    assert voices == [{"voice_id": "elevenlabs_a", "name": "Ada"}]


def test_list_voices_no_key_returns_empty():
    assert list_voices(api_key="") == []


def test_ai33_timeout_error_is_ai33_error_subclass():
    """Ai33TimeoutError, Ai33Error alt sinifi olmali; boylece pytest.raises(Ai33Error) hala yakalar."""
    assert issubclass(Ai33TimeoutError, Ai33Error)


def test_health_check_error_on_plain_ai33_error(tmp_path):
    """Timeout olmayan duz Ai33Error (or. task_id yok) -> 'error' (stalled degil)."""
    sess = FakeSession(post_resp=FakeResponse(200, {"success": True}), task_resps=[])
    assert health_check(voice_id="v", api_key="k", tmp_dir=tmp_path,
                        session=sess, sleep=lambda s: None, now=_clock()) == "error"
