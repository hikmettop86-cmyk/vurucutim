"""Feed kimliği rozeti: KARE SIFIRDA, okunur, kadraj içinde, doğru Türkçeyle.

Rozet küçük resimde görünmezse hiçbir işe yaramaz — tanınma orada olur. Ve rozet
"BILINMEYEN TARIH" yazıyorsa, taşıması gereken özenin yokluğunu ilan eder.
"""
import pytest
from playwright.sync_api import sync_playwright

from short_bot.reel_models import (ReelBeat, ReelNarration, TimedWord,
                                   build_reel_timeline)
from short_bot.reel_render import build_reel_overlay_html

W, H = 1080, 1920
UI_TOP, UI_BOTTOM = 62, 1421     # oynatıcının arayüzü (bkz. test_reel_safe_zone)
FEED_W = 300                      # feed küçük resminin genişliği


def _html(badge="BİLİNMEYEN TARİH #47", cover="Fener Baligi: Olumcul Ask", lang="tr"):
    n = ReelNarration(
        hook="Disi fener baligi erkegi eritir ve bu tesaduf degil.",
        beats=[ReelBeat(text="Erkek disiden yuz kat kucuktur.",
                        visual_query="anglerfish", keyword="yuz kat"),
               ReelBeat(text="Erkek disiye yapisir ve dokular birlesir.",
                        visual_query="anglerfish pair", keyword="birlesme"),
               ReelBeat(text="Artik tek bir canlidirlar.",
                        visual_query="deep sea", keyword="tek canli")],
        close="Iste bu yuzden disi fener baligi erkegi eritir.",
        mood="neutral", peak_beat=1, cover_title=cover)
    words = n.full_text().split()
    asr = [TimedWord(word=w, start_s=i * .5, end_s=i * .5 + .45, seg=-1)
           for i, w in enumerate(words)]
    tl = build_reel_timeline(n, asr, duration_s=len(words) * .5)
    return build_reel_overlay_html(tl, handle="@test",
                                   badge=badge, lang=lang)


_MEASURE = """()=>{
  window.__seek(0);                       // KARE SIFIR: feed'in gösterdiği kare
  const b=document.getElementById('badge');
  const h=document.getElementById('hook');
  const ink=(el)=>{const r=document.createRange();r.selectNodeContents(el);
    const ls=[...r.getClientRects()].filter(x=>x.width>0);
    return {sol:Math.min(...ls.map(x=>x.left)),sag:Math.max(...ls.map(x=>x.right)),
            ust:Math.min(...ls.map(x=>x.top)),alt:Math.max(...ls.map(x=>x.bottom))};};
  return {
    var: !!b,
    acik: b ? b.classList.contains('on') : false,
    metin: b ? b.textContent.trim() : '',
    punto: b ? parseFloat(getComputedStyle(b).fontSize) : 0,
    rozet: b ? ink(b) : null,
    manset: ink(h),
  };}"""


def _olc(html):
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={"width": W, "height": H})
        pg.set_content(html, wait_until="networkidle", timeout=8000)
        pg.evaluate("()=>document.fonts&&document.fonts.ready")
        pg.evaluate("()=>window.__fit()")
        out = pg.evaluate(_MEASURE)
        br.close()
    return out


@pytest.fixture(scope="module")
def m():
    return _olc(_html())


def test_rozet_KARE_SIFIRDA_gorunuyor(m):
    assert m["var"] and m["acik"]
    assert m["metin"] == "BİLİNMEYEN TARİH #47"


def test_rozet_kucuk_resimde_OKUNUYOR(m):
    """Feed'de görünmeyen rozet tanınma sağlamaz — varlık sebebi ortadan kalkar."""
    feed_px = m["punto"] * (FEED_W / W)
    assert feed_px >= 8.0, (
        f"rozet {m['punto']:.0f}pt → küçük resimde {feed_px:.1f}px, okunmaz")


def test_rozet_MANSETE_binmiyor(m):
    assert m["rozet"]["alt"] <= m["manset"]["ust"], (
        f"rozet (alt {m['rozet']['alt']:.0f}) manşetin (üst {m['manset']['ust']:.0f}) "
        f"üstüne biniyor")


def test_rozet_guvenli_bolgede(m):
    assert m["rozet"]["ust"] >= UI_TOP
    assert m["rozet"]["alt"] <= UI_BOTTOM


def test_rozet_kadrajdan_tasmiyor(m):
    assert m["rozet"]["sol"] >= 0 and m["rozet"]["sag"] <= W


def test_uzun_rozet_sigdirilir_kesilmez():
    """nowrap + overflow:hidden sessizce KESERDİ — numarası uçan rozet işlevsizdir."""
    o = _olc(_html(badge="ÇOK UZUN BİR SERİ ADI #128"))
    assert o["rozet"]["sol"] >= 0 and o["rozet"]["sag"] <= W
    assert "#128" in o["metin"]


def test_rozet_yoksa_DOM_da_da_yok():
    o = _olc(_html(badge=""))
    assert not o["var"], "boş rozet için boş bir katman render edilmemeli"


def test_TURKCE_buyuk_harf_dogru(m):
    """CSS text-transform DİLE DUYARLIDIR; lang'sız 'i' → 'I' olur.

    Türkçede 'i' ve 'ı' AYRI harflerdir. "BILINMEYEN" yanlış yazılmış demektir.
    """
    assert "İ" in m["metin"]
    assert "BILINMEYEN" not in m["metin"]


def test_html_lang_niteligi_var():
    html = _html()
    assert 'lang="tr"' in html, "lang yoksa .card'ın uppercase'i de 'i' → 'I' yapar"
