"""flas / flas-narrator: manşet bloğu gövdeyle ÇAKIŞMAMALI.

VAKA (shorts/1763, 2026-08-22): `gundem-yorum` videosunda manşet, beyaz KJ
satırı ve gövde paragrafı 42 saniye boyunca üst üste bindi — okunmuyordu.

Kök neden ölçüldü: `.header` top 640, `.body` top 1070 → blok için 430px var.
Manşet iki satıra kırılınca blok 598px oluyor ve İKİSİ DE `position: absolute`
olduğu için itmek yerine BİNİYOR. Alan başına taşma dedektörü de yakalamıyor,
çünkü tasarlanmış arketiplerin genel bütçesi (header_top ≤3, header_bottom ≤3
satır) 839px'e izin veriyor — mevcut yerin iki katı.

Bu test alan başına satır saymaz; ASIL kısıtı ölçer: iki blok çakışıyor mu.
"""
from __future__ import annotations

import types

import pytest

playwright = pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

TEMPLATES = ("flas.html.j2", "flas-narrator.html.j2")

# shorts/1763'ün GERÇEK script'i — manşeti iki satıra kıran içerik.
UZUN = ("MEVDUAT FAİZİ", "500 BİN TL’NİN GETİRİSİ BELLİ OLDU",
        "32 GÜNLÜK NET KAZANÇLAR AÇIKLANDI")
# Aynı kanalda düzgün çıkan videonun script'i — kıyas noktası.
KISA = ("ALTIN", "7 BİN TL'Yİ AŞTI", "GRAM ALTIN: 7.052 TL")

_OLC_JS = """() => {
  const h = document.querySelector('.header');
  const b = document.querySelector('.body');
  if (!h || !b) return null;
  const hr = h.getBoundingClientRect(), br = b.getBoundingClientRect();
  return {cakisma: Math.max(0, hr.bottom - br.top), header_h: hr.height};
}"""


def _render(tpl_name: str, top: str, bot: str, kj: str) -> str:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    env = Environment(loader=FileSystemLoader("templates"),
                      autoescape=select_autoescape(["html", "j2"]))
    script = types.SimpleNamespace(header_top=top, header_bottom=bot,
                                   photo_overlay=kj, category="EKONOMİ",
                                   body_paragraph="x", highlights=[])
    beat = types.SimpleNamespace(start_s=0.0, end_s=5.0, on_screen=kj)
    narration = types.SimpleNamespace(beats=[beat], duration_s=42.0)
    return env.get_template(tpl_name).render(
        script=script,
        body_html=("Riskiz getiri arayan yurttaşlar için 500 bin TL'nin 32 günlük "
                   "banka getirileri netleşti. Yapılan hesaplamalara göre bankaların "
                   "net kazanç tutarları 10 bin ile 14 bin lira arasında değişiyor."),
        bg_image_url="", colors={}, handle="@GUNDEM", duration_s=6,
        category="EKONOMİ", language="tr", ui_breaking="SON DAKİKA",
        ui_source="Kaynak", dna_css="", animation_style="none",
        rss_source="CUMHURIYET", narration=narration, ticker_items=["A", "B"],
        live_label="CANLI", ticker_label="SIRADA", t=0, now=None)


@pytest.fixture(scope="module")
def sayfa():
    try:
        with sync_playwright() as p:
            tarayici = p.chromium.launch()
            pg = tarayici.new_page(viewport={"width": 1080, "height": 1920})
            yield pg
            tarayici.close()
    except Exception as e:  # noqa: BLE001 — tarayıcı yoksa test atlanır
        pytest.skip(f"playwright kullanılamıyor: {e}")


def _olc(sayfa, tpl_name, script):
    sayfa.set_content(_render(tpl_name, *script), wait_until="load")
    # auto-fit document.fonts.ready'yi bekliyor; ölçümden önce bitmeli.
    sayfa.wait_for_function("() => window.__autoFitDone !== undefined", timeout=10_000)
    sayfa.wait_for_timeout(600)
    return sayfa.evaluate(_OLC_JS)


@pytest.mark.parametrize("tpl_name", TEMPLATES)
def test_uzun_manset_govdeye_binmez(sayfa, tpl_name):
    """shorts/1763'ü kıran içerik. Ölçülen çakışma 168px idi."""
    r = _olc(sayfa, tpl_name, UZUN)
    assert r is not None, f"{tpl_name}: .header / .body bulunamadı"
    assert r["cakisma"] == 0, (
        f"{tpl_name}: manşet gövdeye {r['cakisma']:.0f}px biniyor "
        f"(blok yüksekliği {r['header_h']:.0f}px, izin verilen 430px)")


@pytest.mark.parametrize("tpl_name", TEMPLATES)
def test_kisa_manset_bozulmaz(sayfa, tpl_name):
    """Düzeltme çalışan durumu BOZMAMALI — kısa manşet zaten temizdi."""
    r = _olc(sayfa, tpl_name, KISA)
    assert r["cakisma"] == 0, f"{tpl_name}: kısa manşette çakışma çıktı"


@pytest.mark.parametrize("tpl_name", TEMPLATES)
def test_manset_blogu_ayrilan_yere_sigar(sayfa, tpl_name):
    """Asıl kısıt: .header top 640, .body top 1070 → 430px."""
    r = _olc(sayfa, tpl_name, UZUN)
    assert r["header_h"] <= 430, (
        f"{tpl_name}: manşet bloğu {r['header_h']:.0f}px, ayrılan yer 430px")
