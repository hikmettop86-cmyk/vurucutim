"""ai33 synthesize: HTTP katmani sahte bir Session ile test edilir.

Gercek ag cagrisi YOK. sleep/now enjekte edilir -> testler aninda kosar.
"""
import pytest

from short_bot.tts.ai33_client import (Ai33AuthError, Ai33Error,
                                       Ai33RateLimitError, Ai33TimeoutError,
                                       synthesize)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b""):
        self.status_code = status_code
        self._json = json_data or {}
        self.content = content
        self.text = str(self._json)

    def json(self):
        return self._json


class FakeSession:
    """post -> tek yanit; get -> sirayla verilen yanitlar (url'e gore)."""

    def __init__(self, post_resp, task_resps, audio_resp=None):
        self.post_resp = post_resp
        self.task_resps = list(task_resps)
        self.audio_resp = audio_resp
        self.posts = []
        self.gets = []

    def post(self, url, **kw):
        self.posts.append((url, kw))
        return self.post_resp

    def get(self, url, **kw):
        self.gets.append((url, kw))
        if "/v1/task/" in url:
            return self.task_resps.pop(0)
        return self.audio_resp


def _clock():
    """Her cagrida 1 sn ilerleyen monotonic saat."""
    t = {"v": 0.0}

    def now():
        t["v"] += 1.0
        return t["v"]
    return now


def test_synthesize_happy_path(tmp_path):
    out = tmp_path / "narration.mp3"
    sess = FakeSession(
        post_resp=FakeResponse(200, {"success": True, "task_id": "t1"}),
        task_resps=[
            FakeResponse(200, {"status": "doing"}),
            FakeResponse(200, {"status": "done",
                               "metadata": {"audio_url": "https://cdn/x.mp3"}}),
        ],
        audio_resp=FakeResponse(200, content=b"ID3-fake-mp3"),
    )
    result = synthesize(
        "Merhaba dunya", voice_id="abc123", api_key="sk_test", out_path=out,
        session=sess, sleep=lambda s: None, now=_clock(),
    )
    assert result == out
    assert out.read_bytes() == b"ID3-fake-mp3"

    # POST multipart alanlari: text, voice_id (prefix'li), speed
    url, kw = sess.posts[0]
    assert url == "https://api.ai33.pro/v3/text-to-speech"
    assert kw["headers"]["xi-api-key"] == "sk_test"
    assert kw["files"]["voice_id"][1] == "elevenlabs_abc123"
    assert kw["files"]["text"][1] == "Merhaba dunya"
    assert kw["files"]["speed"][1] == "1"


def test_synthesize_uses_output_uri_fallback(tmp_path):
    out = tmp_path / "n.mp3"
    sess = FakeSession(
        post_resp=FakeResponse(200, {"task_id": "t1"}),
        task_resps=[FakeResponse(200, {"status": "done",
                                       "metadata": {"output_uri": "https://cdn/y.mp3"}})],
        audio_resp=FakeResponse(200, content=b"mp3"),
    )
    synthesize("x", voice_id="v", api_key="k", out_path=out,
               session=sess, sleep=lambda s: None, now=_clock())
    assert out.read_bytes() == b"mp3"


def test_synthesize_task_error_raises(tmp_path):
    sess = FakeSession(
        post_resp=FakeResponse(200, {"task_id": "t1"}),
        task_resps=[FakeResponse(200, {"status": "error",
                                       "error_message": "kredi bitti"})],
    )
    with pytest.raises(Ai33Error, match="kredi bitti"):
        synthesize("x", voice_id="v", api_key="k", out_path=tmp_path / "n.mp3",
                   session=sess, sleep=lambda s: None, now=_clock())


def test_synthesize_401_raises_auth_error(tmp_path):
    sess = FakeSession(post_resp=FakeResponse(401, {}), task_resps=[])
    with pytest.raises(Ai33AuthError):
        synthesize("x", voice_id="v", api_key="bad", out_path=tmp_path / "n.mp3",
                   session=sess, sleep=lambda s: None, now=_clock())


def test_synthesize_429_raises_rate_limit(tmp_path):
    sess = FakeSession(post_resp=FakeResponse(429, {}), task_resps=[])
    with pytest.raises(Ai33RateLimitError):
        synthesize("x", voice_id="v", api_key="k", out_path=tmp_path / "n.mp3",
                   session=sess, sleep=lambda s: None, now=_clock())


def test_synthesize_missing_task_id_raises(tmp_path):
    sess = FakeSession(post_resp=FakeResponse(200, {"success": True}), task_resps=[])
    with pytest.raises(Ai33Error, match="task_id"):
        synthesize("x", voice_id="v", api_key="k", out_path=tmp_path / "n.mp3",
                   session=sess, sleep=lambda s: None, now=_clock())


def test_synthesize_poll_timeout_raises(tmp_path):
    sess = FakeSession(
        post_resp=FakeResponse(200, {"task_id": "t1"}),
        task_resps=[FakeResponse(200, {"status": "doing"})] * 50,
    )
    with pytest.raises(Ai33Error, match="timeout"):
        synthesize("x", voice_id="v", api_key="k", out_path=tmp_path / "n.mp3",
                   session=sess, sleep=lambda s: None, now=_clock(),
                   poll_timeout_s=5.0)


def test_synthesize_poll_timeout_raises_timeout_error(tmp_path):
    """Poll timeout artik Ai33TimeoutError firlatir (Ai33Error alt sinifi)."""
    sess = FakeSession(
        post_resp=FakeResponse(200, {"task_id": "t1"}),
        task_resps=[FakeResponse(200, {"status": "doing"})] * 50,
    )
    with pytest.raises(Ai33TimeoutError, match="timeout"):
        synthesize("x", voice_id="v", api_key="k", out_path=tmp_path / "n.mp3",
                   session=sess, sleep=lambda s: None, now=_clock(),
                   poll_timeout_s=5.0)


class FlakySession(FakeSession):
    """Ses indirme GET'i ilk ``fail_n`` çağrıda ağ hatası fırlatır (10054 benzeri)."""

    def __init__(self, *a, fail_audio_n=0, fail_poll_n=0, **kw):
        super().__init__(*a, **kw)
        self.fail_audio_n = fail_audio_n
        self.fail_poll_n = fail_poll_n

    def get(self, url, **kw):
        if "/v1/task/" in url:
            if self.fail_poll_n > 0:
                self.fail_poll_n -= 1
                raise ConnectionResetError(10054, "connection forcibly closed")
            self.gets.append((url, kw))
            return self.task_resps.pop(0)
        if self.fail_audio_n > 0:
            self.fail_audio_n -= 1
            raise ConnectionResetError(10054, "connection forcibly closed")
        self.gets.append((url, kw))
        return self.audio_resp


def test_synthesize_download_retries_on_connection_reset(tmp_path):
    """Ses üretildi ama indirme koptu (WinError 10054) → retry kurtarır."""
    out = tmp_path / "n.mp3"
    sess = FlakySession(
        post_resp=FakeResponse(200, {"task_id": "t1"}),
        task_resps=[FakeResponse(200, {"status": "done",
                                       "metadata": {"audio_url": "https://cdn/x.mp3"}})],
        audio_resp=FakeResponse(200, content=b"mp3-ok"),
        fail_audio_n=2,          # ilk 2 deneme kopar, 3.sü başarır
    )
    synthesize("x", voice_id="v", api_key="k", out_path=out,
               session=sess, sleep=lambda s: None, now=_clock())
    assert out.read_bytes() == b"mp3-ok"


def test_synthesize_download_fails_after_all_retries(tmp_path):
    sess = FlakySession(
        post_resp=FakeResponse(200, {"task_id": "t1"}),
        task_resps=[FakeResponse(200, {"status": "done",
                                       "metadata": {"audio_url": "https://cdn/x.mp3"}})],
        fail_audio_n=99,         # hiç düzelmiyor
    )
    with pytest.raises(Ai33Error, match="indirme"):
        synthesize("x", voice_id="v", api_key="k", out_path=tmp_path / "n.mp3",
                   session=sess, sleep=lambda s: None, now=_clock())


def test_synthesize_poll_survives_transient_network_error(tmp_path):
    """Poll GET'te geçici ağ kopması üretimi DÜŞÜRMEZ — poll'a devam edilir."""
    out = tmp_path / "n.mp3"
    sess = FlakySession(
        post_resp=FakeResponse(200, {"task_id": "t1"}),
        task_resps=[FakeResponse(200, {"status": "done",
                                       "metadata": {"audio_url": "https://cdn/x.mp3"}})],
        audio_resp=FakeResponse(200, content=b"mp3"),
        fail_poll_n=2,           # ilk 2 poll kopar, sonra done
    )
    synthesize("x", voice_id="v", api_key="k", out_path=out,
               session=sess, sleep=lambda s: None, now=_clock())
    assert out.read_bytes() == b"mp3"


def test_synthesize_empty_text_raises(tmp_path):
    with pytest.raises(ValueError, match="text"):
        synthesize("  ", voice_id="v", api_key="k", out_path=tmp_path / "n.mp3")


def test_synthesize_no_api_key_raises(tmp_path):
    with pytest.raises(Ai33AuthError, match="AI33_API_KEY"):
        synthesize("x", voice_id="v", api_key="", out_path=tmp_path / "n.mp3")


class Http5xxSession(FakeSession):
    """Ses indirme GET'i ilk ``fail_n`` çağrıda 5xx döner (gözlenen: HTTP 503).

    İstisna FIRLATMAZ — geçerli bir yanıt döner; bu yüzden yalnız istisna yakalayan
    retry bunu kaçırıyordu ve tek bir 503 tüm üretimi öldürüyordu.
    """

    def __init__(self, *a, fail_n=0, code=503, **kw):
        super().__init__(*a, **kw)
        self.fail_n = fail_n
        self.code = code

    def get(self, url, **kw):
        if "/v1/task/" in url:
            self.gets.append((url, kw))
            return self.task_resps.pop(0)
        if self.fail_n > 0:
            self.fail_n -= 1
            return FakeResponse(self.code)
        self.gets.append((url, kw))
        return self.audio_resp


def _done_task():
    return [FakeResponse(200, {"status": "done",
                               "metadata": {"audio_url": "https://cdn/x.mp3"}})]


def test_synthesize_download_retries_on_5xx(tmp_path):
    # Ses sunucuda hazır ve kredi harcandı: geçici 503 için vazgeçmek hem parayı
    # hem üretimi çöpe atar.
    out = tmp_path / "n.mp3"
    sess = Http5xxSession(post_resp=FakeResponse(200, {"task_id": "t1"}),
                          task_resps=_done_task(),
                          audio_resp=FakeResponse(200, content=b"mp3-ok"),
                          fail_n=2)
    synthesize("x", voice_id="v", api_key="k", out_path=out,
               session=sess, sleep=lambda s: None, now=_clock())
    assert out.read_bytes() == b"mp3-ok"


def test_synthesize_download_4xx_does_not_retry(tmp_path):
    # 4xx KALICI: beklemek düzeltmez, hemen ve anlaşılır biçimde başarısız ol.
    sess = Http5xxSession(post_resp=FakeResponse(200, {"task_id": "t1"}),
                          task_resps=_done_task(), fail_n=99, code=404)
    with pytest.raises(Ai33Error, match="ses indirme"):
        synthesize("x", voice_id="v", api_key="k", out_path=tmp_path / "n.mp3",
                   session=sess, sleep=lambda s: None, now=_clock())
    assert sess.fail_n == 98      # tek deneme: yeniden denenmedi
