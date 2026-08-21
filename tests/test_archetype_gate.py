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
    for ad in ("stadium", "flas", "eilmeldung", "newscast", "comic", "brutalist"):
        p = Path(f"templates/{ad}.html.j2")
        if not p.exists():
            continue
        ok, sebep = yapi_kapisi(p.read_text(encoding="utf-8"))
        assert ok, f"{ad}: {sebep}"


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
