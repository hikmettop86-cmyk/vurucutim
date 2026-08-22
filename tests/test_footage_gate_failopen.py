"""Fail-open SESSİZ olmamalı — kapıdan geçmeyen klip logsuz kabul ediliyordu.

GERÇEK HATA (short_id=748): 14 farklı klip kabul edildi ama logda YALNIZ 6 vision
yargısı var. Segment 0 ve 5 hiç yargı olmadan 3 klip aldı.

Sebep: küçük resim indirilemezse ``verify_clip_matches`` SESSİZCE True dönüyordu
(``if r.status_code != 200 or not r.content: return True``) — log yok, önbelleğe
yazılmıyor, "kapıdan geçti" sanılıyor. 6 paralel iş parçacığı Pexels CDN'ini
zorlayınca bu yol tetiklendi ve DOĞRULANMAMIŞ klipler videoya girdi.

Fail-open'ın kendisi doğru (üretim asla kapı yüzünden bloklanmaz) — ama SESSİZ
olması yanlış: teşhis ederken "kapı çalışıyor" sanıyorsun.
"""
import short_bot.footage_matcher as fm


class _R:
    def __init__(self, status=200, content=b"jpg"):
        self.status_code = status
        self.content = content


def test_thumbnail_fetch_failure_is_logged_not_silent(monkeypatch, caplog):
    """İndirilemeyen küçük resim → kabul (fail-open) AMA LOGLANIR."""
    monkeypatch.setattr("requests.get", lambda *a, **kw: _R(status=503, content=b""))
    with caplog.at_level("INFO"):
        ok = fm.verify_clip_matches("https://x/a.jpg", "kondor",
                                    vision_call=object(), seen={})
    assert ok is True                       # fail-open korunuyor
    txt = " ".join(r.message for r in caplog.records)
    assert "fail-open" in txt and "küçük resim" in txt, (
        f"sessiz kabul — teşhiste 'kapı çalışıyor' sanılır: {txt!r}")


def test_thumbnail_fetch_is_retried_before_giving_up(monkeypatch):
    """Paralel tarama CDN'i zorluyor — tek bir 503 doğrulamayı ATLATMAMALI."""
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        return _R(status=503, content=b"") if calls["n"] == 1 else _R()

    monkeypatch.setattr("requests.get", flaky)
    monkeypatch.setattr(fm, "_judge_image_file",
                        lambda *a, **kw: fm._FootageVerdict(
                            content="x", matches=True, in_context=True, clear=True))
    ok = fm.verify_clip_matches("https://x/a.jpg", "kondor",
                                vision_call=object(), seen={})
    assert calls["n"] >= 2, "küçük resim yeniden denenmedi"
    assert ok is True                       # ikinci denemede gerçekten yargılandı


def test_network_error_also_logs(monkeypatch, caplog):
    def boom(*a, **kw):
        raise ConnectionError("CDN reddetti")

    monkeypatch.setattr("requests.get", boom)
    with caplog.at_level("INFO"):
        ok = fm.verify_clip_matches("https://x/a.jpg", "kondor",
                                    vision_call=object(), seen={})
    assert ok is True
    txt = " ".join(r.message for r in caplog.records)
    assert "fail-open" in txt
