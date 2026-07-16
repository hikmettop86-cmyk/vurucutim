"""KARE SIFIR: feed'deki küçük resim OKUNABİLİR olmalı.

Feed'de gördüğü ilk kare, izleyicinin durup durmayacağına karar verdiği karedir —
ve video orada ~300px genişliğinde görünür. Bugüne kadar o karede HOOK CÜMLESİ
duruyordu: 140 karaktere kadar, otomatik sığdırma yüzünden 57 puntoya inebilen bir
metin bloğu. Küçük resimde ~16px'e denk gelir; kaydıran göz onu okumaz.

Testler GERÇEK tarayıcıda ölçüyor: iddia değil, piksel.
"""
import pytest
from playwright.sync_api import sync_playwright

from short_bot.reel_models import (COVER_TITLE_MAX_WORDS, ReelBeat, ReelNarration,
                                   TimedWord, build_reel_timeline)
from short_bot.reel_render import build_reel_overlay_html

W, H = 1080, 1920
# Feed küçük resmi ~300px geniş → ölçek 300/1080 = 0.278. Küçük resimde 25px'in
# altındaki bir harf yüksekliği kaydırılırken okunmaz.
FEED_W = 300
MIN_FEED_PX = 25
SAFE_X = 60          # şablondaki kenar payı

_HOOK = "Bir bebek kanguru dogdugunda henuz bir embriyodur ve kendi basina tirmanir."


def _narration(cover=""):
    return ReelNarration(
        hook=_HOOK,
        beats=[ReelBeat(text="Dogumda sadece iki santim boyunda, kor ve sagirdir.",
                        visual_query="kangaroo joey", keyword="IKI SANTIM"),
               ReelBeat(text="Anne yardim etmez, yavru keseye kendi tirmanir.",
                        visual_query="kangaroo pouch", keyword="TIRMANIS"),
               ReelBeat(text="Bu tirmanis uc dakika surer ve hayatinin en zor anidir.",
                        visual_query="kangaroo mother", keyword="UC DAKIKA")],
        close="Iste bu yuzden bebek kanguru bir embriyo olarak dogar.",
        mood="neutral", peak_beat=1, cover_title=cover)


def _html(cover=""):
    n = _narration(cover)
    words = n.full_text().split()
    asr = [TimedWord(word=w, start_s=i * .5, end_s=i * .5 + .45, seg=-1)
           for i, w in enumerate(words)]
    tl = build_reel_timeline(n, asr, duration_s=len(words) * .5)
    return build_reel_overlay_html(tl, handle="@test")


# Kare SIFIRDA ölçüyoruz — feed'in gösterdiği kare tam olarak burasıdır (t=0,
# hook pop'un en büyük olduğu an dahil).
_MEASURE = """()=>{
  window.__seek(0);
  const h=document.getElementById('hook');
  const st=getComputedStyle(h);
  const rg=document.createRange(); rg.selectNodeContents(h);
  const ls=[...rg.getClientRects()].filter(r=>r.width>0);
  return {
    metin: h.textContent.trim(),
    punto: parseFloat(st.fontSize),
    gorunur: h.classList.contains('on'),
    // getClientRects TRANSFORM'U DA İÇERİR → hook pop'un ölçeği ölçüme dahil
    sol: Math.min(...ls.map(r=>r.left)),
    sag: Math.max(...ls.map(r=>r.right)),
    ust: Math.min(...ls.map(r=>r.top)),
    alt: Math.max(...ls.map(r=>r.bottom)),
    altyaziGorunur: [...document.querySelectorAll('.cap .w.vis')].length,
  };}"""


def _olc(html):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H})
        pg.set_content(html, wait_until="networkidle", timeout=8000)
        pg.evaluate("()=>document.fonts&&document.fonts.ready")
        pg.evaluate("()=>window.__fit()")
        out = pg.evaluate(_MEASURE)
        b.close()
    return out


@pytest.fixture(scope="module")
def mansetli():
    return _olc(_html("Bebek kanguru bir embriyo"))


@pytest.fixture(scope="module")
def mansetsiz():
    return _olc(_html(""))


def test_manset_kare_sifirda_gorunuyor(mansetli):
    assert mansetli["gorunur"]
    assert mansetli["metin"] == "Bebek kanguru bir embriyo"


def test_manset_KUCUK_RESIMDE_okunuyor(mansetli):
    """Asıl ölçüm: 300px'lik küçük resme indirgendiğinde harf yüksekliği yeterli mi?"""
    feed_px = mansetli["punto"] * (FEED_W / W)
    assert feed_px >= MIN_FEED_PX, (
        f"manşet {mansetli['punto']:.0f}pt → küçük resimde {feed_px:.1f}px, "
        f"okunması için en az {MIN_FEED_PX}px gerekli")


def test_hook_cumlesi_kucuk_resimde_OKUNMUYORDU(mansetsiz):
    """Eski davranışın NEDEN yetersiz olduğunu ölçüyoruz — gerekçe kayıt altında.

    Manşet olmadan aynı kareye hook CÜMLESİ giriyor; sığdırma onu küçültüyor ve
    küçük resimde okunabilirlik eşiğinin altına düşüyor.
    """
    feed_px = mansetsiz["punto"] * (FEED_W / W)
    assert feed_px < MIN_FEED_PX, (
        "hook cümlesi küçük resimde okunabiliyorsa bu maddenin gerekçesi çürür — "
        "eşiği ya da varsayımı gözden geçir")


def test_manset_kadrajdan_TASMIYOR(mansetli):
    """Hook pop ölçeği DAHİL. Eski 1.15 ölçek, sığdırılmış metni taşırıyordu."""
    assert mansetli["sol"] >= 0, f"manşet soldan taşıyor (x={mansetli['sol']:.0f})"
    assert mansetli["sag"] <= W, f"manşet sağdan taşıyor (x={mansetli['sag']:.0f})"
    # Kadrajın kenarına DAYANMASIN da: küçük resim kırpması pay yemesin
    assert mansetli["sol"] >= 10 and mansetli["sag"] <= W - 10


def test_hook_pop_uzun_metni_de_tasirmiyor(mansetsiz):
    """Manşetsiz (uzun hook) durumda da kare sıfırda taşma olmamalı."""
    assert mansetsiz["sol"] >= 0 and mansetsiz["sag"] <= W


def test_manset_varken_konusulan_hook_ALTYAZI_olarak_akiyor(mansetli):
    """Manşet 3-6 kelime; hook CÜMLESİ kaybolmamalı, altyazı olarak okunmalı."""
    assert mansetli["altyaziGorunur"] > 0, (
        "manşet kartta ama konuşulan hook cümlesi hiçbir yerde görünmüyor")


def test_manset_yokken_eski_davranis_aynen_suruyor(mansetsiz):
    """Fail-open: manşet yoksa kartta hook cümlesi, hook segmentinde altyazı yok."""
    assert mansetsiz["metin"].startswith("Bir bebek kanguru")
    assert mansetsiz["altyaziGorunur"] == 0


# --- MODEL ----------------------------------------------------------------

def test_uzun_manset_KIRPILIR_uretim_dusmez():
    """12 kelimelik bir 'manşet' manşet değildir — ama koca üretimi de çöpe atmayız."""
    n = _narration("Bu cok uzun bir manset ve kesinlikle kirpilmali yoksa okunmaz")
    assert len(n.cover_title.split()) <= COVER_TITLE_MAX_WORDS
    assert n.cover_title.startswith("Bu cok uzun")


def test_manset_bos_birakilabilir():
    assert _narration("").cover_title == ""


def test_manset_zaman_cizelgesine_tasiniyor():
    n = _narration("Bebek kanguru bir embriyo")
    asr = [TimedWord(word=w, start_s=i * .5, end_s=i * .5 + .45, seg=-1)
           for i, w in enumerate(n.full_text().split())]
    tl = build_reel_timeline(n, asr, duration_s=20.0)
    assert tl.cover_title == "Bebek kanguru bir embriyo"


def test_manset_KONUSULMAZ():
    """Manşet ekranda durur, seslendirilmez — TTS metnine sızmamalı."""
    n = _narration("Bebek kanguru bir embriyo")
    assert "Bebek kanguru bir embriyo" not in n.full_text()
    assert n.cover_title not in " ".join(n.segments())
