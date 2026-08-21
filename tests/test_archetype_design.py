"""Arketip tasarım akışı: LLM → kapılar → kaydet (ya da kaydetme).

EN ÖNEMLİ DAVRANIŞ: üç turda kapılardan geçemeyen şablon KAYDEDİLMEZ.
Geçen her şablon diskte kalıcı dosya olur; "olsun bari" diye yazmak, 40
kalıbın yanına 41'inci bozuk kalıbı eklemek ve onu kimsenin temizlememesi
demektir.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_archetype_gate import GECERLI


@pytest.fixture
def sablonlar(tmp_path):
    d = tmp_path / "templates"
    d.mkdir()
    for ad in ("newscast", "flas"):
        (d / f"{ad}.html.j2").write_text(GECERLI, encoding="utf-8")
    return d


def _render_ok(yol, metinler):
    """Her uç metin için bir 'kare' üretir (dosya varlığı yeterli)."""
    out = []
    for i, _ in enumerate(metinler):
        p = Path(yol).parent / f"kare{i}.png"
        p.write_bytes(b"x")
        out.append(p)
    return out


def test_gecerli_sablon_kaydedilir(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    s = tasarla("siyah beyaz, eğik bant", ad="Beşiktaş Mono",
                templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI,
                vision_call=lambda yol: {"sorun": False},
                render_fn=_render_ok)
    assert s.ok, s.sebep
    assert (sablonlar / f"{s.slug}.html.j2").exists()
    assert s.tur == 1


def test_yapi_kapisindan_gecemeyen_KAYDEDILMEZ(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Bozuk", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: "<!DOCTYPE html><html><body>yok</body></html>",
                vision_call=lambda yol: {"sorun": False},
                render_fn=_render_ok)
    assert not s.ok
    assert not (sablonlar / "bozuk.html.j2").exists()
    assert s.tur == 3, "üç tur denenmeliydi"


def test_vision_reddederse_KAYDEDILMEZ(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Tasan", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI,
                vision_call=lambda yol: {"sorun": True, "aciklama": "manşet kesik"},
                render_fn=_render_ok)
    assert not s.ok
    assert "manşet kesik" in s.sebep
    assert not (sablonlar / "tasan.html.j2").exists()


def test_vision_YOKSA_KAYDEDILMEZ(sablonlar, monkeypatch, tmp_path):
    """Fail-closed: denetlenmemiş arketip diske yazılmaz."""
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Denetimsiz", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI, vision_call=None,
                render_fn=_render_ok)
    assert not s.ok
    assert not (sablonlar / "denetimsiz.html.j2").exists()


def test_red_sebebi_BIR_SONRAKI_TURA_yazilir(sablonlar, monkeypatch, tmp_path):
    """Kapı 'geçmedi' demekle kalmamalı; sebep prompt'a girmeli ki tur boşa
    gitmesin."""
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    promptlar = []

    def _llm(p):
        promptlar.append(p)
        return "<!DOCTYPE html><html><body>yok</body></html>"

    tasarla("x", ad="A", templates_dir=sablonlar, settings=None, metin_llm=_llm,
            vision_call=lambda y: {"sorun": False}, render_fn=_render_ok)
    assert len(promptlar) == 3
    assert "REDDEDİLDİ" in promptlar[1]
    assert "body-text" in promptlar[1], "eksik slot bir sonraki tura yazılmadı"


def test_ikinci_turda_duzelirse_kaydedilir(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    n = {"i": 0}

    def _llm(p):
        n["i"] += 1
        return GECERLI if n["i"] == 2 else "<!DOCTYPE html><html></html>"

    s = tasarla("x", ad="Ikinci", templates_dir=sablonlar, settings=None,
                metin_llm=_llm, vision_call=lambda y: {"sorun": False},
                render_fn=_render_ok)
    assert s.ok and s.tur == 2


def test_markdown_citi_temizlenir(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Citli", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: f"İşte şablon:\n```html\n{GECERLI}\n```\nUmarım olur.",
                vision_call=lambda y: {"sorun": False}, render_fn=_render_ok)
    assert s.ok
    icerik = (sablonlar / f"{s.slug}.html.j2").read_text(encoding="utf-8")
    assert icerik.startswith("<!DOCTYPE html>")
    assert "Umarım olur" not in icerik


def test_ornek_sablonlar_prompta_girer(sablonlar, monkeypatch, tmp_path):
    """Tek örnek verince LLM onu kopyalıyor; iki farklı örnek (sade + zengin)
    yapıyı öğretir, görünümü dayatmaz."""
    monkeypatch.chdir(tmp_path)
    from short_bot.archetype_design import tasarla
    p = {}
    tasarla("x", ad="A", templates_dir=sablonlar, settings=None,
            metin_llm=lambda pr: (p.setdefault("ilk", pr), GECERLI)[1],
            vision_call=lambda y: {"sorun": False}, render_fn=_render_ok)
    assert "newscast.html.j2" in p["ilk"] and "flas.html.j2" in p["ilk"]


def test_kaydedilen_arketip_ANINDA_GECERLI_olur(sablonlar, monkeypatch, tmp_path):
    """Kayıt, `dna.py`'nin OKUDUĞU dosyaya yazılmalı ve arketip yeniden
    başlatma beklemeden geçerli olmalı.

    Eski test CWD'ye göre yazılan dosyaya bakıyordu — yani hatanın kendisini
    sabitliyordu. Canlıda `dna.py` başka bir dosyayı, üstelik yalnız import
    anında okuduğu için kanal `unknown archetype` ile reddediliyordu.
    """
    import json
    import short_bot.dna as dna
    yol = tmp_path / "archetypes.json"
    yol.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(dna, "_REGISTRY_PATH", yol)
    for ad in ("ARCHETYPES", "ARCHETYPE_LABELS", "ARCHETYPE_DEFAULTS",
               "_DESIGNED_ARCHETYPES"):
        monkeypatch.setattr(dna, ad, type(getattr(dna, ad))(getattr(dna, ad)))
    monkeypatch.chdir(tmp_path)          # CWD kasten farklı

    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Yeni Kalıp", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI,
                vision_call=lambda y: {"sorun": False}, render_fn=_render_ok)
    assert s.ok
    assert any(a["slug"] == s.slug
               for a in json.loads(yol.read_text(encoding="utf-8")))
    assert s.slug in dna.ARCHETYPES, "yeniden başlatmadan geçerli olmuyor"


# --- ADAY ŞABLON PAYLAŞILAN PARÇALARLA BİRLİKTE RENDER EDİLMELİ ------------
#
# CANLI ARIZA (2026-08-21, ilk gerçek koşu): aday şablon boş bir `tempfile`
# dizinine yazılıp oradan render ediliyordu. Jinja'nın arama yolu şablonun
# BULUNDUĞU dizin (`renderer.py`: FileSystemLoader(template_path.parent)) ve
# orada `_auto_fit.js.j2` yok → `{% include %}` HER denemede patlıyordu:
#
#     3 denemede kapılardan geçemedi. Son sebep: Render sırasında hata:
#     '_auto_fit.js.j2' not found in search path: '...\tmpb3ou2jv1'
#
# Yani Faz III hiçbir zaman çalışmamıştı. Testler sahte `render_fn` enjekte
# ettiği için görünmüyordu — sahte render dizine hiç bakmıyor.

def test_aday_sablon_PAYLASILAN_PARCALARLA_render_edilir(sablonlar, monkeypatch,
                                                         tmp_path):
    monkeypatch.chdir(tmp_path)
    (sablonlar / "_auto_fit.js.j2").write_text("// paylasilan", encoding="utf-8")
    gorulen: list[list[str]] = []

    def _render(yol, metinler):
        gorulen.append(sorted(p.name for p in Path(yol).parent.iterdir()))
        return _render_ok(yol, metinler)

    from short_bot.archetype_design import tasarla
    tasarla("x", ad="Komsulu", templates_dir=sablonlar, settings=None,
            metin_llm=lambda p: GECERLI,
            vision_call=lambda yol: {"sorun": False}, render_fn=_render)
    assert gorulen, "render hiç çağrılmadı"
    assert "_auto_fit.js.j2" in gorulen[0], (
        "aday, paylaşılan parçaların yanında render edilmiyor — "
        f"dizinde yalnız {gorulen[0]}")


def test_render_dizini_TEMIZLENIR(sablonlar, monkeypatch, tmp_path):
    """Şablon dizinine geçici dosya bırakılmamalı: `templates/` kullanıcının
    deposu, 41'inci kalıp orada durmasın."""
    monkeypatch.chdir(tmp_path)
    (sablonlar / "_auto_fit.js.j2").write_text("// paylasilan", encoding="utf-8")
    from short_bot.archetype_design import tasarla
    s = tasarla("x", ad="Temiz", templates_dir=sablonlar, settings=None,
                metin_llm=lambda p: GECERLI,
                vision_call=lambda yol: {"sorun": False}, render_fn=_render_ok)
    kalanlar = sorted(p.name for p in sablonlar.iterdir())
    assert kalanlar == ["_auto_fit.js.j2", "flas.html.j2", "newscast.html.j2",
                        f"{s.slug}.html.j2"], kalanlar


# --- MODEL SÖZLEŞMENİN TAMAMINI GÖRMELİ -----------------------------------
#
# ÖLÇÜLDÜ (2026-08-21): prompt `TEMPLATE-SPEC.md`'yi ilk 6000 karaktere
# kırpıyordu. Ama metni kutuya SIĞDIRMA sözleşmesi çok sonra başlıyor:
#
#     body-text        8531. karakter
#     data-fit-min     8542
#     _auto_fit.js.j2  8836
#     data-fit-width   9321
#     "Zorunlu öğeler" 13345
#
# Yani model, taşmayı önleyen tek mekanizmayı HİÇ görmüyordu ve vision kapısı
# ilk gerçek koşuda üç turun üçünü de "manşet kutusuna sığmayıp kesilmiş"
# diye reddetti. Şans değil, kaçınılmazdı. Spec 14 KB — Opus için hiçbir şey.

def test_prompt_SPECIN_TAMAMINI_tasir(sablonlar, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    imza = "SIGDIRMA-SOZLESMESI-BURADA"
    (tmp_path / "TEMPLATE-SPEC.md").write_text(
        "x" * 9000 + imza + "y" * 4000, encoding="utf-8")
    gorulen: list[str] = []

    from short_bot.archetype_design import tasarla
    tasarla("x", ad="Spec", templates_dir=sablonlar, settings=None,
            metin_llm=lambda p: (gorulen.append(p), GECERLI)[1],
            vision_call=lambda yol: {"sorun": False}, render_fn=_render_ok)
    assert gorulen, "model hiç çağrılmadı"
    assert imza in gorulen[0], (
        "spec kırpılıyor — sığdırma sözleşmesi modele hiç ulaşmıyor")


def test_prompt_CALISAN_ORNEKLERI_de_tasir(sablonlar, monkeypatch, tmp_path):
    """Örnekler kırpılmamalı: yapı oradan öğreniliyor."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "TEMPLATE-SPEC.md").write_text("spec", encoding="utf-8")
    gorulen: list[str] = []
    from short_bot.archetype_design import tasarla
    tasarla("x", ad="Ornek", templates_dir=sablonlar, settings=None,
            metin_llm=lambda p: (gorulen.append(p), GECERLI)[1],
            vision_call=lambda yol: {"sorun": False}, render_fn=_render_ok)
    assert "newscast.html.j2" in gorulen[0] and "flas.html.j2" in gorulen[0]


# --- MODEL NEYE GÖRE YARGILANDIĞINI BİLMELİ --------------------------------
#
# ÖLÇÜLDÜ (2026-08-21): prompt kabul ölçütünü hiç söylemiyordu. Daha kötüsü,
# "ÇALIŞAN ÖRNEKLER — yapıyı bunlardan al" diye verilen üç şablonun ÜÇÜ DE
# vision kapısından geçmiyor (aynı uç metinlerle sınandı):
#
#   stadium  REDDEDİLDİ  manşet sağ kenarda kesilmiş, SON DAKİKA rozetiyle
#                        çakışıyor, gövdenin son satırı solarak kesiliyor
#   flas     REDDEDİLDİ  bant ve şerit gövde metninin üstüne binmiş
#   newscast REDDEDİLDİ  gövdenin son satırı alt kenarda yarıya kesilmiş
#
# Yani örneği birebir taklit etmek REDDEDİLMEK demekti ve model bunu
# bilmiyordu.

def test_prompt_KABUL_OLCUTUNU_ve_UZUNLUKLARI_soyler(sablonlar, monkeypatch,
                                                     tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "TEMPLATE-SPEC.md").write_text("spec", encoding="utf-8")
    gorulen: list[str] = []
    from short_bot.archetype_design import tasarla
    tasarla("x", ad="Olcut", templates_dir=sablonlar, settings=None,
            metin_llm=lambda p: (gorulen.append(p), GECERLI)[1],
            vision_call=lambda yol: {"sorun": False}, render_fn=_render_ok)
    p = gorulen[0]
    for beklenen in ("25", "35", "40", "300"):
        assert beklenen in p, f"sığdırılacak uzunluk {beklenen} söylenmiyor"
    assert "data-fit-width" in p
    # NOT: `str.lower()` Türkçe değil ("TAŞIYOR" → "taşiyor"); büyük harfle ara.
    assert "TAŞIYOR" in p and "GEÇMİYOR" in p, (
        "örneklerin bu kapıdan geçmediği söylenmiyor — model onları taklit eder")


def test_slug_TURKCE_HARFLERI_dusurmez():
    """Şablon adı KALICI dosya adı. `re.sub("[^a-zA-Z0-9]+", "-", ...)` Türkçe
    harfleri komple siliyordu: canlıda "Bayern Münih" → `bayern-m-nih.html.j2`
    (ü düştü, yerine tire kaldı). `channel_chat._slugify` bunu doğru yapıyor —
    aynı eşleme tablosu burada da olmalı."""
    from short_bot.archetype_design import _slugify
    assert _slugify("Bayern Münih") == "bayern-munih"
    assert _slugify("Beşiktaş Gündem") == "besiktas-gundem"
    assert _slugify("Işık & Gölge") == "isik-golge"
    assert _slugify("") == "arketip"
