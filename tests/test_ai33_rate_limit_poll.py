"""Poll sırasındaki 429 üretimi DÜŞÜRMEMELİ — görev zaten gönderildi, KREDİ HARCANDI.

GERÇEK HATA: ai33 poll'ü 429 ("hız sınırı aşıldı veya kuyruk dolu") döndü ve
sentezleme fırlattı → koşu iptal. Ama o noktada TTS görevi ZATEN SUNUCUYA
GÖNDERİLMİŞTİ ve sunucuda işleniyordu: krediyi ödedik, sonucu terk ettik.

429 poll'de GEÇİCİDİR: geri çekil, beklemeye devam et. Üstteki ``poll_timeout_s``
zaten sonsuz beklemeyi engelliyor.

AYRIM: POST (görev gönderme) sırasındaki 429 farklıdır — henüz bir şey
gönderilmedi, kredi harcanmadı; orada hata vermek doğru.
"""
import pytest

from short_bot.tts.ai33_client import Ai33RateLimitError, synthesize


class _Resp:
    def __init__(self, status=200, payload=None, content=b"mp3"):
        self.status_code = status
        self._payload = payload or {}
        self.content = content

    def json(self):
        return self._payload


class _Sess:
    """POST → task_id; GET → verilen sırayla yanıt döndürür."""

    def __init__(self, gets):
        self._gets = list(gets)
        self.get_calls = 0

    def post(self, url, **kw):
        return _Resp(200, {"task_id": "t1"})

    def get(self, url, **kw):
        self.get_calls += 1
        r = self._gets.pop(0) if self._gets else _Resp(200, {"status": "done"})
        if isinstance(r, Exception):
            raise r
        return r


def _synth(sess, tmp_path, **kw):
    sleeps = []
    out = synthesize("metin", voice_id="v", api_key="k",
                     out_path=tmp_path / "o.mp3", session=sess,
                     sleep=lambda s: sleeps.append(s), now=lambda: 0.0, **kw)
    return out, sleeps


def test_rate_limit_during_poll_is_backed_off_not_fatal(tmp_path):
    """429 → bekle, POLL'E DEVAM ET. Görev sunucuda; krediyi çöpe atma."""
    done = _Resp(200, {"status": "done",
                       "metadata": {"audio_url": "https://x/a.mp3"}})
    sess = _Sess([_Resp(429), _Resp(429), done, _Resp(200, content=b"mp3data")])
    out, sleeps = _synth(sess, tmp_path)
    assert out.exists()
    assert sess.get_calls >= 3, "429'dan sonra poll bırakıldı"
    assert any(s > 1 for s in sleeps), "geri çekilme yok — sunucuyu daha da zorlar"


def test_rate_limit_backoff_grows(tmp_path):
    """Arka arkaya 429'da bekleme UZAMALI (sabit aralık sunucuyu zorlar)."""
    done = _Resp(200, {"status": "done",
                       "metadata": {"audio_url": "https://x/a.mp3"}})
    sess = _Sess([_Resp(429), _Resp(429), _Resp(429), done,
                  _Resp(200, content=b"mp3data")])
    _out, sleeps = _synth(sess, tmp_path)
    backoffs = [s for s in sleeps if s > 1]
    assert len(backoffs) >= 2 and backoffs[1] > backoffs[0]


def test_rate_limit_on_submit_still_raises(tmp_path):
    """POST'ta 429: henüz bir şey gönderilmedi, kredi harcanmadı → hata ver."""
    class _S(_Sess):
        def post(self, url, **kw):
            return _Resp(429)

    with pytest.raises(Ai33RateLimitError):
        _synth(_S([]), tmp_path)


def test_poll_timeout_still_guards_against_endless_429(tmp_path):
    """Servis sürekli 429 veriyorsa sonsuza kadar bekleme."""
    sess = _Sess([_Resp(429)] * 200)
    t = {"now": 0.0}

    def now():
        t["now"] += 30.0
        return t["now"]

    from short_bot.tts.ai33_client import Ai33TimeoutError
    with pytest.raises(Ai33TimeoutError):
        synthesize("metin", voice_id="v", api_key="k",
                   out_path=tmp_path / "o.mp3", session=sess,
                   sleep=lambda s: None, now=now, poll_timeout_s=120)
