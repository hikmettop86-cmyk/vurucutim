"""Poll sırasındaki 5xx üretimi DÜŞÜRMEMELİ — görev zaten gönderildi, KREDİ HARCANDI.

GERÇEK HATA (koşu 1246, dayidiyorki): ai33 poll'ü HTTP 503
``{"code":"server_busy","message":"Task polling temporarily busy"}`` döndü;
istemci bunu KALICI sayıp fırlattı → preflight 'error' → aday düştü. Ölçüm:
30 poll isteğinin 14'ü (%47) 503. Sonuç: üst üste 5 aday elendi, tek video
üretilemedi, her denemede TTS kredisi yandı — oysa servis SAĞLIKLIYDI
(aynı anda elle yapılan sentez 4sn'de 'done' verdi).

5xx poll'de GEÇİCİDİR (429 ile aynı gerekçe): görev SUNUCUDA işleniyor,
kredi ödendi; geri çekil, beklemeye devam et. ``poll_timeout_s`` zaten
sonsuz beklemeyi engelliyor.

AYRIMLAR:
  • POST'taki 5xx farklı — henüz görev gönderilmedi, kredi harcanmadı;
    orada hata vermek doğru (üst katman preflight'ı yeniden dener).
  • Poll'deki 4xx KALICIDIR (ör. 404 task yok) — beklemenin faydası yok.
"""
import pytest

from short_bot.tts.ai33_client import Ai33Error, Ai33TimeoutError, synthesize


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


def _done():
    return _Resp(200, {"status": "done", "metadata": {"audio_url": "https://x/a.mp3"}})


def _synth(sess, tmp_path, **kw):
    sleeps = []
    out = synthesize("metin", voice_id="v", api_key="k",
                     out_path=tmp_path / "o.mp3", session=sess,
                     sleep=lambda s: sleeps.append(s), now=lambda: 0.0, **kw)
    return out, sleeps


def test_server_busy_503_during_poll_is_backed_off_not_fatal(tmp_path):
    """503 → bekle, POLL'E DEVAM ET. Görev sunucuda; krediyi çöpe atma."""
    sess = _Sess([_Resp(503), _Resp(503), _done(), _Resp(200, content=b"mp3data")])
    out, sleeps = _synth(sess, tmp_path)
    assert out.exists()
    assert sess.get_calls >= 3, "503'ten sonra poll bırakıldı"
    assert any(s > 1 for s in sleeps), "geri çekilme yok — sunucuyu daha da zorlar"


def test_gateway_5xx_during_poll_also_survives(tmp_path):
    """502/504 de geçici ağ geçidi hatası — aynı yol."""
    sess = _Sess([_Resp(502), _Resp(504), _done(), _Resp(200, content=b"mp3data")])
    out, _sleeps = _synth(sess, tmp_path)
    assert out.exists()


def test_server_busy_backoff_grows(tmp_path):
    """Arka arkaya 503'te bekleme UZAMALI (sabit aralık meşgul sunucuyu zorlar)."""
    sess = _Sess([_Resp(503), _Resp(503), _Resp(503), _done(),
                  _Resp(200, content=b"mp3data")])
    # poll aralığını küçült ki uzayan bekleme SADECE geri çekilmeden gelsin
    _out, sleeps = _synth(sess, tmp_path, poll_interval_s=0.1)
    backoffs = [s for s in sleeps if s > 0.1]
    assert len(backoffs) >= 2 and backoffs[1] > backoffs[0]


def test_poll_timeout_still_guards_against_endless_503(tmp_path):
    """Servis gerçekten çökmüşse sonsuza kadar bekleme."""
    sess = _Sess([_Resp(503)] * 200)
    t = {"now": 0.0}

    def now():
        t["now"] += 30.0
        return t["now"]

    with pytest.raises(Ai33TimeoutError):
        synthesize("metin", voice_id="v", api_key="k",
                   out_path=tmp_path / "o.mp3", session=sess,
                   sleep=lambda s: None, now=now, poll_timeout_s=120)


def test_4xx_during_poll_still_raises(tmp_path):
    """Poll'de 404 KALICIDIR (task yok) — beklemek anlamsız, hemen hata ver."""
    sess = _Sess([_Resp(404)])
    with pytest.raises(Ai33Error):
        _synth(sess, tmp_path)


def test_health_check_survives_realistic_503_storm(tmp_path):
    """Preflight bütçesi 503 fırtınasına YETMELİ — yoksa 'stalled' der ve
    üst katman krediyi yeniden yakarak preflight'ı tekrarlar.

    Ölçülen gerçeklik: poll isteklerinin ~yarısı 503; arka arkaya 5 tanesi
    (2+4+6+8+10 = 30sn geri çekilme + poll aralıkları) sıra dışı değil.
    Sağlıklı servis bu yüzden 'stalled' sayılmamalı.
    """
    from short_bot.tts.ai33_client import health_check

    t = {"now": 0.0}

    def now():
        return t["now"]

    def sleep(s):
        t["now"] += s   # gerçek saat gibi: beklemek bütçeden yer

    sess = _Sess([_Resp(503)] * 5 + [_done(), _Resp(200, content=b"mp3data")])
    assert health_check(voice_id="v", api_key="k", tmp_dir=tmp_path,
                        session=sess, sleep=sleep, now=now) == "healthy"


def test_5xx_on_submit_still_raises(tmp_path):
    """POST'ta 5xx: görev gönderilmedi, kredi harcanmadı → hata ver."""
    class _S(_Sess):
        def post(self, url, **kw):
            return _Resp(503)

    with pytest.raises(Ai33Error):
        _synth(_S([]), tmp_path)
