"""HOOK KLİBİ ayrıca ÇARPICI olmalı — sadece "alakalı ve net" yetmez.

GERÇEK HATA (short_id=756, kirpi balığı): videonun İLK 4.3 SANİYESİ neredeyse
siyah, boş bir su altı sahnesiydi. Kapıdan geçti çünkü:
  - alakalıydı (mercan resifi, konu balık)
  - "clear" idi (tamamen karanlık değil, seçilebiliyor)
Ama HOOK'un işi alakalı olmak değil — KAYDIRMAYI DURDURMAK.

Araştırma: kare sıfır videonun EN ÇARPICI karesi olmalı ve SESSİZ OKUNABİLMELİ
(izlemelerin çoğu sessiz başlıyor). Boş/karanlık bir açılış karesi, TTS daha ilk
kelimesini söylemeden kaydırılır — ve o kaydırma YouTube'un sıralama zincirindeki
İLK halkadır ("izlemeyi seçti mi, görmezden mi geldi?").

Bu yüzden hook klibi için AYRI ve DAHA YÜKSEK bir eşik var: ``striking``.
Beat klipleri bundan MUAF — orada alaka + netlik yeter.
"""
import short_bot.footage_matcher as fm


class _R:
    status_code = 200
    content = b"jpg"


def _verdict(**kw):
    base = dict(content="an empty dark reef", matches=True, in_context=True,
                clear=True, striking=False)
    base.update(kw)
    return fm._FootageVerdict(**base)


def test_hook_gate_rejects_a_dull_but_relevant_clip(monkeypatch):
    """Alakalı + net AMA çarpıcı DEĞİL → hook için REDDEDİLİR."""
    monkeypatch.setattr("requests.get", lambda *a, **kw: _R())
    monkeypatch.setattr(fm, "_judge_image_file",
                        lambda *a, **kw: _verdict(striking=False))
    ok = fm.verify_clip_matches("https://x/a.jpg", "puffer fish",
                                vision_call=object(), seen={}, hook=True)
    assert ok is False, "sıkıcı klip HOOK'a girdi — kaydırma orada başlar"


def test_the_same_clip_is_fine_for_a_beat(monkeypatch):
    """Beat'ler çarpıcılık aramaz — alaka + netlik yeter."""
    monkeypatch.setattr("requests.get", lambda *a, **kw: _R())
    monkeypatch.setattr(fm, "_judge_image_file",
                        lambda *a, **kw: _verdict(striking=False))
    ok = fm.verify_clip_matches("https://x/a.jpg", "puffer fish",
                                vision_call=object(), seen={})
    assert ok is True


def test_striking_clip_passes_the_hook_gate(monkeypatch):
    monkeypatch.setattr("requests.get", lambda *a, **kw: _R())
    monkeypatch.setattr(fm, "_judge_image_file",
                        lambda *a, **kw: _verdict(striking=True))
    assert fm.verify_clip_matches("https://x/a.jpg", "puffer fish",
                                  vision_call=object(), seen={}, hook=True) is True


def test_prompt_asks_about_striking():
    p = fm._judge_prompt("puffer fish", context="kirpi balığı")
    assert "striking" in p
    # Sessiz izleme gerekçesi prompt'ta olmalı (soyut kural tek başına yetmiyor).
    # NOT: Türkçe .lower() tuzağı — "SESSİZ".lower() "sessi̇z" verir (nokta kalır),
    # o yüzden ham metinde arıyoruz.
    assert "SESSİZ" in p and "KAYDIRIR" in p


def test_cache_key_separates_hook_from_beat(monkeypatch):
    """Aynı klip hook'ta reddedilip beat'te kabul edilebilir — önbellek KARIŞTIRMASIN."""
    monkeypatch.setattr("requests.get", lambda *a, **kw: _R())
    calls = []

    def judge(path, query, *, vision_call, context=""):
        calls.append(1)
        return _verdict(striking=False)

    monkeypatch.setattr(fm, "_judge_image_file", judge)
    seen: dict = {}
    assert fm.verify_clip_matches("https://x/a.jpg", "q", vision_call=object(),
                                  seen=seen, hook=True) is False
    assert fm.verify_clip_matches("https://x/a.jpg", "q", vision_call=object(),
                                  seen=seen) is True
    assert len(calls) == 1, "yargı aynı — vision'a iki kez gitmeye gerek yok"
