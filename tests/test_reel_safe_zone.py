"""YouTube Shorts güvenli bölgesi: oynatıcının arayüzü bizim yazımızı yemesin.

Video 1080x1920 üretilse de OYNATICI onun ÜSTÜNE kendi arayüzünü çizer. Gerçek bir
telefondan ölçüldü (Shorts, 917x2048 ekran → video y 136-1803 arasına oturuyor):
kanal adı 1421-1502, başlık 1525-1588, "Yapay zeka" rozeti 1611-1680, görüntülenme
1697-1767, üst bar 0-62.

GERÇEK HATA: altyazılar (y 1440-1620), ABONE ÇİPİ (y 1620-1690) ve handle (1730-1790)
tam bu bandın içindeydi — izleyici abone çağrısını HİÇ GÖRMÜYORDU.
"""
import pytest
from playwright.sync_api import sync_playwright

from short_bot.reel_models import (ReelBeat, ReelNarration, TimedWord,
                                   build_reel_timeline)
from short_bot.reel_render import build_reel_overlay_html

W, H = 1080, 1920
UI_TOP = 62        # üst bar (geri / arama / menü)
UI_BOTTOM = 1421   # kanal adı satırının başladığı yer — altı tamamen oynatıcının

# Her katmanı AYNI ANDA görünür kılıp en kötü durumu ölçüyoruz: gerçek videoda
# hepsi aynı karede olmasa da hiçbiri tehlike bandına girmemeli.
MEASURE = """()=>{
  document.getElementById('hook').classList.add('on');
  document.querySelector('.card').classList.add('on');
  const np=document.getElementById('numpop');
  np.classList.add('on'); np.textContent='12';
  [...document.querySelectorAll('.cap .w')].slice(4,7).forEach(w=>w.classList.add('vis'));
  const out={};
  const add=(k,el)=>{const r=el.getBoundingClientRect(); out[k]=[r.top,r.bottom];};
  add('bar',document.getElementById('bar'));
  add('kart',document.querySelector('.card'));
  add('numpop',np);
  add('handle',document.getElementById('handle'));
  const rs=[...document.querySelectorAll('.cap .w.vis')].map(e=>e.getBoundingClientRect());
  out['altyazi']=[Math.min(...rs.map(r=>r.top)),Math.max(...rs.map(r=>r.bottom))];
  // hook/close metninin mürekkep alt sınırı (punto sığdırmadan sonra)
  const h=document.getElementById('hook');
  const rg=document.createRange(); rg.selectNodeContents(h);
  const ls=[...rg.getClientRects()].filter(r=>r.width>0);
  out['hook']=[Math.min(...ls.map(r=>r.top)),Math.max(...ls.map(r=>r.bottom))];
  return out;}"""


def _html(hook="Sigara içtiğinizde vücudunuzda anında bunlar olur."):
    n = ReelNarration(
        hook=hook,
        beats=[ReelBeat(text="Kan damarların daralıyor ve parmak uçlarına kan gitmiyor.",
                        visual_query="blood vessel", keyword="KAN DAMARLARI"),
               ReelBeat(text="Beyinde 12 saniyede dopamin patlaması olur.",
                        visual_query="brain", keyword="DOPAMİN"),
               ReelBeat(text="Kalp atışın dakikada 20 kez artar.",
                        visual_query="heart", keyword="KALP")],
        close="İşte bu yüzden sigara seni sakinleştirmez.", mood="neutral")
    words = n.full_text().split()
    asr = [TimedWord(word=w, start_s=i * .5, end_s=i * .5 + .45, seg=-1)
           for i, w in enumerate(words)]
    tl = build_reel_timeline(n, asr, duration_s=len(words) * .5)
    return build_reel_overlay_html(tl, handle="@icerdeneleroluyor")


@pytest.fixture(scope="module")
def boxes():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H})
        pg.set_content(_html(), wait_until="networkidle", timeout=8000)
        pg.evaluate("()=>document.fonts&&document.fonts.ready")
        pg.evaluate("()=>window.__fit()")
        out = pg.evaluate(MEASURE)
        b.close()
    return out


# handle LİSTEDE YOK — BİLEREK. Kullanıcı onu altta istedi: oynatıcının kanal/başlık
# satırının altında kalıp çoğu zaman görünmüyor, ama önemli değil (YouTube zaten
# kanal adını gösteriyor) ve üst-sağa taşımak kadrajın temiz köşesini harcıyordu.
# İZLEYİCİYE LAZIM OLAN katmanlar (altyazı, hook) güvenli bölgede.
# (Beğeni/abone çipleri 2026-07-16'da kaldırıldı — katman listesinden düştüler.)
@pytest.mark.parametrize("katman", ["bar", "kart", "hook", "numpop", "altyazi"])
def test_katman_oynaticinin_arayuzune_girmiyor(boxes, katman):
    top, bottom = boxes[katman]
    assert bottom <= UI_BOTTOM, (
        f"{katman} y={bottom:.0f} → oynatıcının kanal/başlık bandının ({UI_BOTTOM}) "
        f"altında kalıyor, izleyici GÖREMEZ")
    assert top >= UI_TOP, (
        f"{katman} y={top:.0f} → oynatıcının üst barının ({UI_TOP}) altında kalıyor")


def test_handle_altta_ve_kadraj_icinde(boxes):
    # Konumu tercih meselesi; tek şart kadrajdan taşmaması.
    top, bottom = boxes["handle"]
    assert 0 <= top and bottom <= 1920



