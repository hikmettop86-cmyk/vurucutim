"""ASCII'ye indirgenemeyen başlıklar ayırt edilebilir dosya adı üretmeli.

ÖLÇÜLDÜ (2026-08-22, Japonca kanalın ilk gerçek koşusu): _slugify her Japonca
başlığı boşa indirgeyip "haber" yedeğine düşüyordu. Sonuç: klasör haber.mp4,
haber-2.mp4, haber-3.mp4 diye dolacaktı — hangi videonun hangisi olduğu
dosya adından okunamaz, üstelik "haber" Japonca kanalda Türkçe bir kelime.
"""
from __future__ import annotations

JA = ["布施博の事務所 芸能プロダクションが破産開始決定",
      "藤井風 タイ公演中止を発表",
      "中川翔子 双子の息子が二歩歩いた"]


def test_japonca_basliklar_birbirinden_ayrilir():
    from short_bot.pipeline import _slugify
    sluglar = [_slugify(t) for t in JA]
    assert len(set(sluglar)) == 3, f"başlıklar aynı slug'a düştü: {sluglar}"
    assert not any(s == "haber" for s in sluglar)


def test_ayni_baslik_ayni_slug_uretir():
    """Yol üretim başında BİR KEZ seçilip denemeler paylaşıyor — kararlı olmalı."""
    from short_bot.pipeline import _slugify
    assert _slugify(JA[0]) == _slugify(JA[0])


def test_slug_dosya_adinda_guvenli():
    from short_bot.pipeline import _slugify
    import re
    for t in JA:
        assert re.fullmatch(r"[a-z0-9-]+", _slugify(t)), _slugify(t)


def test_latin_basliklar_degismedi():
    from short_bot.pipeline import _slugify
    # MEVCUT davranış: Türkçe ı/ş NFKD ile çözülmüyor, tamamen düşüyor
    # ("altın" -> "alt-n"). Bu ayrı bir konu; burada DEĞİŞMEDİĞİ doğrulanıyor.
    assert _slugify("Altın 7 Bin TL'yi Aştı") == "alt-n-7-bin-tl-yi-ast"
    assert _slugify("Galatasaray transfer") == "galatasaray-transfer"


def test_bos_baslik_hala_yedege_duser():
    from short_bot.pipeline import _slugify
    assert _slugify("") == "haber"
    assert _slugify("   ") == "haber"
