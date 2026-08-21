"""Arketip kapıları: LLM'e şablon yazdırmanın denetimi.

"LLM şablon yazınca tutarlı çıkmıyor" doğru bir gözlem ama çözümü LLM'i
kısıtlamak değil. Render DETERMİNİSTİK (Playwright chromium, aynı HTML her
zaman aynı kare); öyleyse yazdırdığın şeyi GÖRÜP denetleyebilirsin.

Desen projede kanıtlanmış — footage_matcher (MAX_GATE_CHECKS=24) ve
image_picker._verify_with_claude aynısını yapıyor. Burası üçüncü kapı.

ÜÇ AŞAMA:
  1. yapı kapısı  — düz kontrol, bedava. Zorunlu slot ve değişkenler duruyor mu.
  2. render       — chromium, ÜÇ UÇ METİNLE (tek örnek metin yanıltıyor).
  3. vision kapısı — kareye bakar: manşet sığıyor mu, okunuyor mu.
"""
from __future__ import annotations

import pytest

# Sözleşmeye uyan asgari şablon (TEMPLATE-SPEC bölüm 7'nin özü).
GECERLI = """<!DOCTYPE html>
<html lang="{{ language }}">
<head><meta charset="utf-8"><style>
{{ dna_css|safe }}
html, body { width: 1080px; height: 1920px; }
/* Kanalın DNA paletine cevap ver — yoksa rengi/fontu ekrana yansımaz. */
.top { color: var(--primary); font-family: var(--font-headline); }
.bot { color: var(--accent); }
.body-text { color: var(--text-main); font-family: var(--font-body); }
.progress::after { animation: fill {{ duration_s }}s linear forwards; }
</style></head>
<body>
<div class="stage">
  <div class="header">
    <span class="top" data-fit-width="40">{{ script.header_top }}</span>
    <span class="bot">{{ script.header_bottom }}</span>
  </div>
  <div class="photo"><div class="bg-img"></div></div>
  <div class="body"><div class="body-text" data-fit-min="36" data-fit-max="48">{{ body_html|safe }}</div></div>
  <div class="progress"></div>
  <div class="handle">{{ handle }}</div>
</div>
{% include "_auto_fit.js.j2" %}
</body></html>"""


def test_gecerli_sablon_gecer():
    from short_bot.archetype_gate import yapi_kapisi
    ok, sebep = yapi_kapisi(GECERLI)
    assert ok, sebep


@pytest.mark.parametrize("eksik", [
    'class="body-text"', 'class="handle"', 'class="progress"',
    'class="bg-img"',
])
def test_eksik_slot_reddedilir(eksik):
    """`_auto_fit.js` bu sınıflara bakarak manşeti küçültüyor; biri yoksa
    metin sessizce taşar."""
    from short_bot.archetype_gate import yapi_kapisi
    ok, sebep = yapi_kapisi(GECERLI.replace(eksik, 'class="bozuk"'))
    assert not ok
    assert eksik.split('"')[1] in sebep, sebep


@pytest.mark.parametrize("eksik", [
    "{{ script.header_top }}", "{{ body_html|safe }}", "{{ handle }}",
    "{{ dna_css|safe }}",
])
def test_eksik_degisken_reddedilir(eksik):
    """Değişkeni yazmayan şablon render olur ama BOŞ kare verir."""
    from short_bot.archetype_gate import yapi_kapisi
    ok, sebep = yapi_kapisi(GECERLI.replace(eksik, ""))
    assert not ok


def test_auto_fit_include_zorunlu():
    from short_bot.archetype_gate import yapi_kapisi
    ok, sebep = yapi_kapisi(GECERLI.replace('{% include "_auto_fit.js.j2" %}', ""))
    assert not ok
    assert "auto_fit" in sebep


def test_data_fit_niteligi_zorunlu():
    """Nitelik yoksa JS'in küçültecek bir hedefi olmaz."""
    from short_bot.archetype_gate import yapi_kapisi
    ok, sebep = yapi_kapisi(GECERLI.replace('data-fit-min="36" data-fit-max="48"', ""))
    assert not ok
    assert "data-fit" in sebep


def test_viewport_boyutu_zorunlu():
    from short_bot.archetype_gate import yapi_kapisi
    ok, sebep = yapi_kapisi(GECERLI.replace("width: 1080px; height: 1920px;", ""))
    assert not ok
    assert "1080" in sebep


def test_calisan_sablonlar_KAPIDAN_GECER():
    """Kapı ezbere değil, GERÇEĞE göre kalibre: ilk sürüm TEMPLATE-SPEC'in
    örnek iskeletindeki her sınıfı zorunlu tutuyordu ve `comic`i reddediyordu —
    oysa comic çalışıyor, sadece .panel-header/.panel kullanıyor.

    Çalışan bir şablonu reddeden kapı, yeni şablonu da haksız yere reddeder."""
    from pathlib import Path

    from short_bot.archetype_gate import yapi_kapisi
    # NOT: `comic` bu listeden ÇIKARILDI — `var(--font-headline)` kullanmıyor,
    # yani kanalın manşet fontu ona yansımıyor (ölçüldü 2026-08-21). Kapının
    # hatası değil, comic'in eksiği; ama kalibrasyon listesi tam bar'ı geçen
    # şablonlardan oluşmalı.
    for ad in ("brutalist", "editorial", "minimal", "tabloid", "galatasaray"):
        p = Path(f"templates/{ad}.html.j2")
        if not p.exists():
            continue
        ok, sebep = yapi_kapisi(p.read_text(encoding="utf-8"))
        assert ok, f"{ad}: {sebep}"


def test_CLAMPLI_SABLONLAR_kapiyi_BILEREK_gecemez():
    """Kapı burada BİLEREK üretimdeki bazı şablonların ÜSTÜNDE duruyor.

    `stadium`, `flas`, `newscast`, `eilmeldung` gövdede `-webkit-line-clamp`
    kullanıyor ve ÖLÇÜLDÜ (2026-08-21): stadium'dan clamp+maske kaldırılınca
    267 karakterlik gövdenin TAMAMI taşmadan göründü — yani clamp SIĞAN metni
    kesiyordu. Bu şablonların kesmesi bir olgu, kapının hatası değil.

    Kalibrasyon ilkesi ("çalışan şablonu reddeden kapı yeni şablonu da haksız
    reddeder") YAPISAL kontroller için geçerli; bu kural bilinçli bir kalite
    yükseltmesi. Yeni şablon eskisinden İYİ olmalı.
    """
    from pathlib import Path

    from short_bot.archetype_gate import yapi_kapisi
    for ad in ("stadium", "flas", "newscast", "eilmeldung"):
        p = Path(f"templates/{ad}.html.j2")
        if not p.exists():
            continue
        ok, sebep = yapi_kapisi(p.read_text(encoding="utf-8"))
        assert not ok and "clamp" in sebep.lower(), f"{ad}: {sebep}"
        # BAŞKA bir eksiği olmamalı — yapısal kalibrasyon hâlâ doğru.
        for baska in ('class="', "{{ ", "viewport", "_auto_fit.js.j2",
                      "data-fit-min ve data-fit-max"):
            assert baska not in sebep, f"{ad} clamp DIŞINDA da düşüyor: {sebep}"


def test_sebep_LLM_E_GERI_YAZILABILIR():
    """Kapı 'geçmedi' demekle kalmamalı — neyin eksik olduğunu söylemeli ki
    bir sonraki tur düzeltilebilsin."""
    from short_bot.archetype_gate import yapi_kapisi
    ok, sebep = yapi_kapisi("<html><body>hiçbir şey</body></html>")
    assert not ok
    assert len(sebep) > 30
    for beklenen in ("body-text", "handle"):
        assert beklenen in sebep


# --- uç metinler -----------------------------------------------------------

def test_uc_metinler_farkli_uzunlukta():
    """Tek örnek metinle test etmek yanıltıyor: kısa manşetle geçen şablon
    uzun manşette taşar. Bugünkü smoke_render_dna tam bunu yapıyordu."""
    from short_bot.archetype_gate import UC_METINLER
    assert len(UC_METINLER) >= 3
    basliklar = [len(s.header_top + s.header_bottom) for s in UC_METINLER]
    assert max(basliklar) > 2 * min(basliklar), "uçlar birbirine çok yakın"
    govdeler = [len(s.body_paragraph) for s in UC_METINLER]
    assert max(govdeler) > 2 * min(govdeler)


def test_uc_metinler_gecerli_script():
    from short_bot.archetype_gate import UC_METINLER
    from short_bot.models import Script
    for s in UC_METINLER:
        assert isinstance(s, Script)


# --- vision kapısı ---------------------------------------------------------

def test_vision_kesik_manseti_reddeder():
    from short_bot.archetype_gate import vision_kapisi
    ok, sebep = vision_kapisi(
        [__file__],  # dosya varlığı yeterli; vision sahte
        vision_call=lambda yol: {"sorun": True, "aciklama": "manşet kutuya sığmıyor"})
    assert not ok
    assert "sığmıyor" in sebep


def test_vision_temiz_kareyi_gecirir():
    from short_bot.archetype_gate import vision_kapisi
    ok, _ = vision_kapisi([__file__],
                          vision_call=lambda yol: {"sorun": False, "aciklama": ""})
    assert ok


def test_vision_YOKSA_KAPI_KAPALI():
    """footage_matcher'dan FARKLI: orada vision yoksa fail-open (üretim
    durmamalı). Burada fail-CLOSED — bozuk şablon diske yazılmamalı."""
    from short_bot.archetype_gate import vision_kapisi
    ok, sebep = vision_kapisi([__file__], vision_call=None)
    assert not ok
    assert "vision" in sebep.lower()


def test_vision_TEK_karede_sorun_bulursa_reddeder():
    """Üç kareden biri bozuksa şablon bozuktur."""
    from short_bot.archetype_gate import vision_kapisi
    sayac = {"n": 0}

    def _v(yol):
        sayac["n"] += 1
        return {"sorun": sayac["n"] == 2, "aciklama": "ikinci kare taşmış"}

    ok, sebep = vision_kapisi([__file__, __file__, __file__], vision_call=_v)
    assert not ok
    assert "ikinci kare" in sebep


# --- UÇ METİNLER MODELİN SINIRLARINDA DURMALI ------------------------------
#
# FATAL BULGU (2026-08-21, üç canlı koşu): `Script` modeli `header_top`'ı 25,
# `header_bottom`'ı 35 karakterde KIRPIYOR (models._TRIM_LIMITS — bilinçli:
# bir karakterlik taşma koca bir üretimi düşürmesin). Uç metinler 44 ve 56
# karakterdi; fixture'ın KENDİSİ kelime ortasından kesiliyordu:
#
#     'ÇOK UZUN BİR MANŞET ÜST S'   ← 'ÜST SATIRI BURADA DURUYOR' kesildi
#     'Ve alt satırı da en az onun kadar u'
#
# Vision kapısı doğal olarak her adayı "manşet kelime ortasında kesilmiş"
# diye reddetti — HİÇBİR şablon geçemezdi. Üretimdeki `stadium` bile geçmedi
# (aynı kareyle sınandı).
#
# ÖLÇÜM (1159 üretim senaryosu, shorts.script_json):
#     header_top     p50 11  p90 17  p99 23  max 25
#     header_bottom  p50 24  p90 30  p99 34  max 35
#     photo_overlay  p50 19  p90 26  p99 34  max 40
#     body_paragraph p50 181 p90 226 p99 261 max 302   (model limiti 800 —
#                                                       üretimde hiç görülmüyor)

def test_UC_METINLER_model_tarafindan_KIRPILMIYOR():
    from short_bot.archetype_gate import UC_HAM, UC_METINLER
    from short_bot.models import Script
    assert len(UC_HAM) == len(UC_METINLER)
    for ham, s in zip(UC_HAM, UC_METINLER):
        for alan, deger in ham.items():
            if alan == "dil":          # fixture meta, Script alanı değil
                continue
            assert getattr(s, alan) == deger, (
                f"{alan} kırpıldı: {deger!r} -> {getattr(s, alan)!r} — "
                f"uç metin modelin sınırını aşıyor, kapı hiçbir şablonu geçirmez")


def test_UC_METINLER_URETIMIN_UST_SINIRLARINI_zorlar():
    """Sınırın çok altında kalan fixture da işe yaramaz: kısa metinle geçen
    şablon uzun manşette taşar. Ölçülen üretim maksimumlarına yakın olmalı."""
    from short_bot.archetype_gate import UC_METINLER
    en_uzun = {a: max(len(getattr(s, a)) for s in UC_METINLER)
               for a in ("header_top", "header_bottom", "photo_overlay",
                         "body_paragraph")}
    assert en_uzun["header_top"] >= 24, en_uzun          # üretim max 25
    assert en_uzun["header_bottom"] >= 34, en_uzun       # üretim max 35
    assert en_uzun["photo_overlay"] >= 34, en_uzun       # üretim max 40
    assert 250 <= en_uzun["body_paragraph"] <= 400, en_uzun   # üretim max 302


# --- GÖVDE KESİLMEMELİ: line-clamp YASAK -----------------------------------
#
# ÖLÇÜLDÜ (2026-08-21, canlı): arketip tasarımı Trabzonspor kanalında 3 turda
# geçemedi, sebep hep aynıydı — "gövde metninin alt kısmı çerçevenin dışına
# taşarak kesilmiş". Mekanizmayı deneyle çözdük:
#
#   `stadium.html.j2` .body-text kuralında `-webkit-line-clamp: 9` var (artı
#   alt kenarda solma maskesi). Bu SABİT SATIR SAYISI — `_auto_fit` fontu
#   küçültse bile 9. satırdan sonrası kesilir. `data-fit-min`'i 38'den 24'e
#   düşürmek HİÇBİR ŞEYİ değiştirmedi (aynı kare çıktı).
#
#   Aynı şablondan clamp + maske kaldırılınca 267 karakterlik gövdenin TAMAMI
#   göründü, taşma yok, ilerleme çubuğu/handle ile çakışma yok. Yani clamp
#   SIĞAN metni kesiyordu.
#
# Depodaki 34 şablonun 26'sı zaten clamp kullanmıyor; yasak ev üslubuna aykırı
# değil. Bu kontrol BEDAVA (render/vision harcamadan) ve sebebi modele geri
# yazılıyor.

_GOVDE_CLAMPLI = """<!DOCTYPE html><html><head><style>
html,body{width:1080px;height:1920px}
.body-text{display:-webkit-box;-webkit-line-clamp:9;-webkit-box-orient:vertical;overflow:hidden;color:var(--text-main);font-family:var(--font-body)}
.top{color:var(--primary);font-family:var(--font-headline)}
.bot{color:var(--accent)}
</style></head><body>
<div class="top">{{ script.header_top }}</div>
<div class="bot">{{ script.header_bottom }}</div>
<div class="bg-img"></div>
<div class="body"><div class="body-text" data-fit-min="26" data-fit-max="42"
  data-fit-pad="20">{{ body_html }}</div></div>
<div class="progress"></div><div class="handle">{{ handle }}</div>
<style>{{ dna_css }}</style><span>{{ duration_s }}</span>
{% include "_auto_fit.js.j2" %}</body></html>"""


def test_GOVDE_CLAMPI_reddedilir():
    from short_bot.archetype_gate import yapi_kapisi
    ok, sebep = yapi_kapisi(_GOVDE_CLAMPLI)
    assert not ok
    assert "clamp" in sebep.lower()


def test_clampsiz_sablon_gecer():
    from short_bot.archetype_gate import yapi_kapisi
    ok, sebep = yapi_kapisi(_GOVDE_CLAMPLI.replace(
        "-webkit-line-clamp:9;", ""))
    assert ok, sebep


def test_BASKA_yerdeki_clamp_serbest():
    """Yasak yalnız GÖVDE için: manşette clamp kullanmak meşru olabilir."""
    from short_bot.archetype_gate import yapi_kapisi
    s = _GOVDE_CLAMPLI.replace(
        ".body-text{display:-webkit-box;-webkit-line-clamp:9;",
        ".top{-webkit-line-clamp:2}\n.body-text{display:-webkit-box;")
    ok, sebep = yapi_kapisi(s)
    assert ok, sebep


# --- STRES MATRİSİ ---------------------------------------------------------
#
# KULLANICI KURALI (2026-08-21): "her yönü ile stres testleri yapmalı".
# Üç metin yetmiyordu: fotoğrafsız kare, tek kelimelik manşet, uzun handle,
# CJK ve aksanlı diller HİÇ sınanmıyordu. Bunların hepsi canlıda var
# (japonca kanal, almanca kanal, ispanyolca kanal).

def test_matris_YETERINCE_genis():
    from short_bot.archetype_gate import UC_METINLER
    assert len(UC_METINLER) >= 7, f"yalnız {len(UC_METINLER)} durum"


def test_matris_UC_UZUNLUKLARI_kapsar():
    from short_bot.archetype_gate import UC_METINLER
    ht = [len(s.header_top) for s in UC_METINLER]
    gv = [len(s.body_paragraph) for s in UC_METINLER]
    assert min(ht) <= 6, "tek kelimelik manşet sınanmıyor"
    assert max(ht) >= 24, "en uzun manşet sınanmıyor"
    assert min(gv) <= 30 and max(gv) >= 250


def test_matris_CJK_ve_AKSANLI_dilleri_kapsar():
    """CJK fontu olmayan şablon TOFU basar; aksanlı harfler düşen font
    yedeklerinde kayboluyor (ölçüldü: 'MANŞET' → 'MANSET')."""
    from short_bot.archetype_gate import UC_METINLER
    hepsi = " ".join(s.header_top + s.header_bottom + s.body_paragraph
                     for s in UC_METINLER)
    assert any("\u3040" <= c <= "\u9fff" for c in hepsi), "CJK yok"
    assert any(c in hepsi for c in "ÇĞİÖŞÜ"), "Türkçe aksan yok"
    assert any(c in hepsi for c in "äöüßáéíóñ"), "Avrupa aksanı yok"


def test_matris_TUM_MODLARI_kapsar():
    from short_bot.archetype_gate import UC_METINLER
    assert {s.mood for s in UC_METINLER} >= {"breaking", "neutral"}


def test_matris_HEPSI_modelden_kirpilmadan_gecer():
    from short_bot.archetype_gate import UC_HAM, UC_METINLER
    for ham, s in zip(UC_HAM, UC_METINLER):
        for alan, deger in ham.items():
            if alan == "dil":
                continue
            assert getattr(s, alan) == deger, f"{alan} kırpıldı: {deger!r}"


# --- ŞABLON KANALIN PALETİNE CEVAP VERMELİ ---------------------------------
#
# ÖLÇÜLDÜ (2026-08-21): AI'ın ürettiği `amerika-gundemi` beş DNA değişkeninden
# DÖRDÜNÜ, `bursaspor-kart` `--primary`yi kullanmıyor. Sonuç: kanalın paleti
# ekrana YANSIMIYOR — Spotify dilinde üretilen aday Trabzonspor kanalında da
# Spotify yeşili kalıyor.
#
# İki kullanıcı kuralını birden çiğniyor: "önizleme = gerçek çıktı" (kanalın
# paletiyle çizilen kare ile şablonun kendi rengi tutmuyor) ve "şablonlar
# birbirine benzemesin" (aynı arketipi kullanan iki kanal aynı görünür).
#
# 42 şablonun 33-38'i bu değişkenleri zaten kullanıyor; kural ev üslubu.

_PALETSIZ = """<!DOCTYPE html><html><head><style>
html,body{width:1080px;height:1920px}
.top{color:#fff;font-family:Arial}
.body-text{font-size:40px}
</style></head><body>
<div class="top">{{ script.header_top }}</div>
<div class="bot">{{ script.header_bottom }}</div>
<div class="bg-img"></div>
<div class="body"><div class="body-text" data-fit-min="26" data-fit-max="42"
  data-fit-pad="20">{{ body_html }}</div></div>
<div class="progress"></div><div class="handle">{{ handle }}</div>
<style>{{ dna_css }}</style><span>{{ duration_s }}</span>
{% include "_auto_fit.js.j2" %}</body></html>"""


def test_DNA_DEGISKENLERINI_kullanmayan_reddedilir():
    from short_bot.archetype_gate import yapi_kapisi
    ok, sebep = yapi_kapisi(_PALETSIZ)
    assert not ok
    assert "--primary" in sebep or "palet" in sebep.lower()


def test_DNA_degiskenlerini_kullanan_gecer():
    from short_bot.archetype_gate import yapi_kapisi
    s = _PALETSIZ.replace(
        ".top{color:#fff;font-family:Arial}",
        ".top{color:var(--primary);font-family:var(--font-headline)}\n"
        ".bot{color:var(--accent);font-family:var(--font-body)}\n"
        ".body-text{color:var(--text-main)}")
    ok, sebep = yapi_kapisi(s)
    assert ok, sebep


def test_KULLANICININ_URETTIGI_sablonlar_bu_kurala_takiliyor():
    """Bulguyu sabitle: bu iki şablon canlıda üretildi ve paleti yok sayıyor.
    Kural olmasa aynı hata her yeni kanalda tekrarlanırdı."""
    from pathlib import Path
    from short_bot.archetype_gate import yapi_kapisi
    for ad in ("amerika-gundemi", "bursaspor-kart"):
        p = Path(f"templates/{ad}.html.j2")
        if not p.exists():
            continue
        ok, sebep = yapi_kapisi(p.read_text(encoding="utf-8"))
        assert not ok and ("--primary" in sebep or "palet" in sebep.lower()), \
            f"{ad}: {sebep}"
