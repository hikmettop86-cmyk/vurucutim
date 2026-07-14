"""Metnin kadraja sığdırılması.

Gerçek hata (short 758): hook kartının kelimeleri sağdan ve soldan kesildi. Uzun
bir Türkçe kelime ("düşündüğümüzden") kutudan geniş olabiliyor; CSS onu satır
sonuna kaydıramaz, sessizce TAŞIRIR. Kelimeyi ortadan kırmak Türkçede okunmaz hâle
getirdiği için çözüm puntoyu küçültmek.

ÖLÇÜM scrollWidth İLE YAPILAMAZ: metin ortalı olduğunda satır kutudan iki yana EŞİT
taşar ve scrollWidth yalnız SAĞ taşmayı sayar — 960px kutuda 1086px'lik bir satır
için scrollWidth hâlâ 960 döner (ölçüldü, short 759'un hook'u). Bu yüzden satırların
GERÇEK mürekkep sınırlarına bakıyoruz.
"""
import pytest
from playwright.sync_api import sync_playwright

from short_bot.reel_models import ReelBeat, ReelNarration, build_reel_timeline
from short_bot.reel_render import build_reel_overlay_html

W, H = 1080, 1920
SAFE_X = 60           # şablondaki kenar payı

# Satırların gerçek sol/sağ sınırı. Hook normalde display:none — gizli elemanın
# ölçüsü sıfırdır, ölçüm için görünür kılıyoruz. Altyazıda kelimeler tek tek gizli.
PROBE = """(sel)=>{
  const el = sel==='hook' ? document.getElementById('hook')
                          : document.querySelector('.cap');
  const d = el.style.display;
  if (sel==='hook') el.style.display='block'; else el.classList.add('measure');
  const rg=document.createRange(); rg.selectNodeContents(el);
  const ls=[...rg.getClientRects()].filter(r=>r.width>0);
  const out={size:parseFloat(getComputedStyle(el).fontSize),
             left:Math.round(Math.min(...ls.map(r=>r.left))),
             right:Math.round(Math.max(...ls.map(r=>r.right)))};
  if (sel==='hook') el.style.display=d; else el.classList.remove('measure');
  return out;}"""


def _tl(hook, beat):
    n = ReelNarration(
        hook=hook,
        beats=[ReelBeat(text=beat, visual_query="brain scan", keyword="BEYİN"),
               ReelBeat(text="Sinyaller saniyede yüz metre ilerler.",
                        visual_query="synapse", keyword="HIZ"),
               ReelBeat(text="Beyin bunu hiç durmadan yönetir.",
                        visual_query="neuron", keyword="AĞ")],
        close="İşte beynin gizli hızı.", mood="upbeat")
    return build_reel_timeline(n, [], duration_s=float(n.word_count()))


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(); yield b; b.close()


def _measure(browser, hook, beat, sel="hook"):
    pg = browser.new_page(viewport={"width": W, "height": H})
    pg.set_content(build_reel_overlay_html(_tl(hook, beat), handle="@t"),
                   wait_until="networkidle", timeout=8000)
    pg.evaluate("()=>document.fonts&&document.fonts.ready")
    before = pg.evaluate(PROBE, sel)
    pg.evaluate("()=>window.__fit()")
    after = pg.evaluate(PROBE, sel)
    pg.evaluate("()=>window.__fit()")
    again = pg.evaluate(PROBE, sel)
    pg.close()
    return before, after, again


def _fits(m):
    return m["left"] >= SAFE_X - 1 and m["right"] <= W - SAFE_X + 1


UZUN_KELIME = "Beynimiz, düşündüğümüzden çok daha hızıyla çalışıyor olabilir."
ORTALI_TASMA = "Sigara içtiğinizde vücudunuzda anında bunlar olur."
KISA_HOOK = "Beyin çok hızlı çalışır."
KISA_BEAT = "Sinir sistemi komut taşır."
UZUN_BEAT = "Elektroensefalografiyle beyin dalgaları ölçülebiliyormuş."


def test_tek_uzun_kelime_sigana_kadar_kuculur(browser):
    before, after, _ = _measure(browser, UZUN_KELIME, KISA_BEAT)
    assert not _fits(before)            # hata gerçekten var
    assert _fits(after)                 # ve kapandı
    assert after["size"] < before["size"]


def test_ortali_simetrik_tasma_da_yakalanir(browser):
    # scrollWidth bunu GÖRMÜYOR (kutu 960, scrollWidth 960 — ama satır 1086px).
    # Mürekkep ölçümü olmadan bu vaka sessizce kadraj dışına taşardı.
    before, after, _ = _measure(browser, ORTALI_TASMA, KISA_BEAT)
    assert before["left"] < SAFE_X and before["right"] > W - SAFE_X
    assert _fits(after)


def test_sigan_hook_kuculmez(browser):
    # Sığdırma yalnız GEREKİRSE devreye girmeli: her videoyu küçültmek kusur olurdu.
    before, after, _ = _measure(browser, KISA_HOOK, KISA_BEAT)
    assert _fits(before)
    assert after["size"] == before["size"]


def test_altyazidaki_uzun_kelime_de_sigdirilir(browser):
    before, after, _ = _measure(browser, KISA_HOOK, UZUN_BEAT, sel="cap")
    assert not _fits(before)
    assert _fits(after)


def test_sigan_altyazi_kuculmez(browser):
    before, after, _ = _measure(browser, KISA_HOOK, KISA_BEAT, sel="cap")
    assert after["size"] == before["size"]


def test_fit_idempotent(browser):
    # Kareler tek bir __fit'ten sonra çekilir; punto çağrı sayısına bağlı olursa
    # render deterministik olmaktan çıkar.
    _, after, again = _measure(browser, UZUN_KELIME, UZUN_BEAT)
    assert again == after


# --- ÖBEK SARMASI (dar yerleşim) --------------------------------------------
# Altyazı her an EN FAZLA 3 kelime ("öbek") gösterir. Dar bir kutuda (lower_left:
# 800px — sağdaki YouTube eylem rayından kaçmak için) metin TAŞMAZ, SARAR; ve sarma
# taşma olmadığı için lineOverflow onu GÖREMEZ.
# GERÇEK SONUÇ (bölüm #1, lower_left): "Bir kilogramlık bir" — üç kelime, ÜÇ SATIR.
#
# SINIR 2 SATIR ve bu GEOMETRİK: altyazı bottom:540'tan yukarı büyür; 3 satır üst
# kenarı y≈1097'ye çıkarır, abone çipi ise y 1080-1160'ta → ÇAKIŞMA.

_LINE_PROBE = """()=>{
  const cap=document.querySelector('.cap');
  const ws=[...cap.querySelectorAll('.w')];
  const obekler=[...new Set(ws.map(w=>w.dataset.chunk))];
  let enKotu=1;
  for(const c of obekler){
    for(const w of ws) w.classList.toggle('vis', w.dataset.chunk===c);
    const s=new Set();
    for(const w of ws) if(w.classList.contains('vis'))
      s.add(Math.round(w.getBoundingClientRect().top));
    enKotu=Math.max(enKotu, s.size);
  }
  for(const w of ws) w.classList.remove('vis');
  return {satir:enKotu, punto:parseFloat(getComputedStyle(cap).fontSize)};}"""

# Abone çipinin alt kenarı (şablon: #cta bottom:760 → y 1080-1160)
CTA_BOTTOM_Y = 1160

_CAP_TOP = """()=>{
  const cap=document.querySelector('.cap');
  const ws=[...cap.querySelectorAll('.w')];
  const obekler=[...new Set(ws.map(w=>w.dataset.chunk))];
  let ust=9999;
  for(const c of obekler){
    for(const w of ws) w.classList.toggle('vis', w.dataset.chunk===c);
    for(const w of ws) if(w.classList.contains('vis'))
      ust=Math.min(ust, w.getBoundingClientRect().top);
  }
  for(const w of ws) w.classList.remove('vis');
  return ust;}"""


def _cap_olc(browser, layout, probe=_LINE_PROBE):
    pg = browser.new_page(viewport={"width": W, "height": H})
    tl = _tl(KISA_HOOK, "Bir kilogramlık bir kedi çok daha fazla kalori yakabilir.")
    pg.set_content(build_reel_overlay_html(tl, handle="@t", layout=layout,
                                           cta_text="ABONE OL"),
                   wait_until="networkidle", timeout=8000)
    pg.evaluate("()=>document.fonts&&document.fonts.ready")
    once = pg.evaluate(probe)
    pg.evaluate("()=>window.__fit()")
    sonra = pg.evaluate(probe)
    pg.close()
    return once, sonra


def test_dar_yerlesimde_obek_3_satira_bolunmez(browser):
    once, sonra = _cap_olc(browser, "lower_left")
    assert once["satir"] > 2, (
        "dar kutuda öbek zaten 2 satıra sığıyorsa bu düzeltmenin gerekçesi çürür")
    assert sonra["satir"] <= 2, f"öbek hâlâ {sonra['satir']} satır"
    assert sonra["punto"] < once["punto"], "sığdırma hiç devreye girmemiş"


def test_sigdirilmis_altyazi_ABONE_CIPINE_binmiyor(browser):
    """2 satır sınırının GEREKÇESİ: 3 satırlık altyazı çipin üstüne biniyordu."""
    once, sonra = _cap_olc(browser, "lower_left", probe=_CAP_TOP)
    assert once < CTA_BOTTOM_Y, "çakışma yoksa sınırın gerekçesi çürür"
    assert sonra >= CTA_BOTTOM_Y, (
        f"altyazının üstü y={sonra:.0f} → abone çipine ({CTA_BOTTOM_Y}) biniyor")


def test_genis_yerlesimde_gereksiz_kuculme_yok(browser):
    once, sonra = _cap_olc(browser, "classic")
    if once["satir"] <= 2:
        assert sonra["punto"] == once["punto"], "2 satıra sığan altyazı küçültülmemeli"


# --- ÖBEK BOYUTU FONTTAN ÖNCE FEDA EDİLİR -----------------------------------
# GERÇEK HATA (short 801, gartengeheimnisse, Almanca, lower_left): öbek 3 kelimede
# SABİTTİ ve sığdırma yalnız FONTU küçültüyordu. Almanca bileşik kelimelerde
# ("jahrzehntelang", "Blütenblätter") bu çöktü: font TABANA (48px) indi ve altyazı
# YİNE 3 satır sardı — hem okunmaz, hem 3. satır abone çipine bindi.
#
# Telefonda okunabilirliği belirleyen şey PUNTO; kelime sayısı pazarlık edilebilir.
# Bu yüzden sıra tersine çevrildi: önce öbeği (3→2→1) küçült, fontu koru.
# ÖLÇÜLDÜ: 2 kelimeye inince punto 48px → 82px (%71 artış), satır 3 → 2.
# 1 kelimeye inmek HİÇBİR ŞEY kazandırmıyor (yine 82px), o yüzden taban 1 değil
# "sığan EN BÜYÜK öbek".

ALMANCA = ("Die Betrachtung als kulinarische Pflanze wurde jahrzehntelang "
           "unterschätzt und ihre Blütenblätter werden zu Sirup verkocht.")

_OBEK_PROBE = """()=>{
  const cap=document.querySelector('.cap');
  const ws=[...cap.querySelectorAll('.w')];
  const obekler=[...new Set(ws.map(w=>w.dataset.chunk))];
  let enCok=0, enKotu=1;
  for(const c of obekler){
    const g=ws.filter(w=>w.dataset.chunk===c);
    enCok=Math.max(enCok, g.length);
    for(const w of ws) w.classList.toggle('vis', w.dataset.chunk===c);
    const s=new Set();
    for(const w of ws) if(w.classList.contains('vis'))
      s.add(Math.round(w.getBoundingClientRect().top));
    enKotu=Math.max(enKotu, s.size);
  }
  for(const w of ws) w.classList.remove('vis');
  return {kelime:enCok, satir:enKotu,
          punto:parseFloat(getComputedStyle(cap).fontSize)};}"""

TABAN_PUNTO = 82        # şablondaki .cap font-size
IYI_PUNTO = TABAN_PUNTO * 0.85


def _obek_olc(browser, beat, layout, lang):
    pg = browser.new_page(viewport={"width": W, "height": H})
    pg.set_content(build_reel_overlay_html(_tl(KISA_HOOK, beat), handle="@t",
                                           layout=layout, lang=lang,
                                           cta_text="ABONE OL"),
                   wait_until="networkidle", timeout=8000)
    pg.evaluate("()=>document.fonts&&document.fonts.ready")
    once = pg.evaluate(_OBEK_PROBE)
    pg.evaluate("()=>window.__fit()")
    sonra = pg.evaluate(_OBEK_PROBE)
    pg.close()
    return once, sonra


def test_uzun_kelimeli_dilde_obek_kucultulur_font_korunur(browser):
    once, sonra = _obek_olc(browser, ALMANCA, "lower_left", "de")
    assert once["kelime"] == 3, "başlangıç öbeği 3 kelime olmalı"
    assert once["satir"] > 2, "3 kelime zaten sığıyorsa düzeltmenin gerekçesi çürür"
    assert sonra["kelime"] < 3, (
        f"öbek küçültülmemiş ({sonra['kelime']} kelime) — font feda edilmiş demektir")
    assert sonra["satir"] <= 2, f"öbek hâlâ {sonra['satir']} satır"
    assert sonra["punto"] >= IYI_PUNTO, (
        f"punto {sonra['punto']:.0f}px — kelime bırakmak yerine font feda edilmiş")


def test_tek_kelimeye_kadar_inmez(browser):
    """1 kelime, 2 kelimeden DAHA BÜYÜK punto vermiyor (ölçüldü) — bağlamı harcamayalım."""
    _, sonra = _obek_olc(browser, ALMANCA, "lower_left", "de")
    assert sonra["kelime"] >= 2, "sığan en büyük öbek seçilmeli, en küçüğü değil"


def test_kisa_kelimeli_dilde_obek_3_kalir(browser):
    """Türkçe regresyon: kelimeler kısa, 3 kelime iyi puntoda sığıyor → dokunma."""
    _, sonra = _obek_olc(browser, KISA_BEAT, "lower_left", "tr")
    assert sonra["kelime"] == 3, "gereksiz yere öbek küçültülmüş"
    assert sonra["punto"] == TABAN_PUNTO, "gereksiz yere font küçültülmüş"
