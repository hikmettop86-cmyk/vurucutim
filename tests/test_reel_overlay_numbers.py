from short_bot.reel_models import ReelTimeline, TimedWord
from short_bot.reel_render import build_reel_overlay_html


def _timeline():
    words = [TimedWord(word="Beyni", start_s=0.0, end_s=0.5, seg=0),
             TimedWord(word="240", start_s=1.0, end_s=1.5, seg=1),
             TimedWord(word="parçaya", start_s=1.5, end_s=2.0, seg=1),
             TimedWord(word="bölündü", start_s=2.0, end_s=2.5, seg=2)]
    return ReelTimeline(words=words, seg_spans=[(0, 1), (1, 2), (2, 3)],
                        seg_queries=[None, "q", None], seg_keywords=["", "K", ""],
                        duration_s=3.0, hook="Hook", close="Close")


def test_numbers_layer_rendered_when_given():
    html = build_reel_overlay_html(
        _timeline(),
        numbers=[{"text": "240 parçaya", "start_s": 1.0, "end_s": 2.0}])
    assert 'id="numpop"' in html
    assert "240 parçaya" in html


def test_numbers_in_dedup_signature():
    """Sayı pop + hook pop __sig'e dâhil olmalı — yoksa kare-dedup bu kareleri
    kaçırır (aynı imza sanıp önceki kareyi kopyalar → vurgu görünmez).

    İmza fonksiyonunun TAMAMINA bakıyoruz, ilk N karakterine değil: eski hâli
    [:900] diliyordu ve imzaya yeni bir satır eklenince (rozet) kırıldı — oysa
    aradığı şey hâlâ oradaydı.
    """
    html = build_reel_overlay_html(
        _timeline(), numbers=[{"text": "240", "start_s": 1.0, "end_s": 2.0}])
    sig_body = html.split("window.__sig")[1].split("window.__seek(0)")[0]
    assert "NP" in sig_body                    # sayı katmanı imzada
    assert "HOOK.style.transform" in sig_body  # hook pop imzada


def test_no_numbers_layer_when_empty():
    html = build_reel_overlay_html(_timeline(), numbers=[])
    assert "const NUMS=[];" in html.replace(" ", "").replace("constNUMS", "const NUMS")


def _numpop_at(html, t_s):
    """Verilen saniyede numpop GERÇEKTEN görünüyor mu — tarayıcıda ölç."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1080, "height": 1920})
        pg.set_content(html, wait_until="domcontentloaded")
        pg.evaluate("(ms)=>window.__seek(ms)", int(t_s * 1000))
        out = pg.evaluate("()=>{const n=document.getElementById('numpop');"
                          "return {acik:n.classList.contains('on'),metin:n.textContent};}")
        b.close()
    return out


def test_numpop_suppressed_on_hook_and_close():
    """Sayı popu hook/close segmentinde GÖSTERİLMEZ — orada büyük başlık bloğu
    var, sayı onun üstüne biniyordu (gerçek üretim hatası).

    KAYNAK METNİ DEĞİL DAVRANIŞI ölçüyoruz: eski hâli JS'te 'if(capOn){for(const n
    of NUMS)' dizgisini arıyordu ve değişken adı değişince kırıldı — oysa davranış
    doğruydu. Bir testin uygulamanın harflerine değil, sonucuna bakması gerekir.
    """
    # Aynı sayı hem hook (seg 0, t=0.3) hem beat (seg 1, t=1.2) penceresinde tanımlı
    html = build_reel_overlay_html(
        _timeline(), numbers=[{"text": "240", "start_s": 0.1, "end_s": 0.5},
                              {"text": "240", "start_s": 1.0, "end_s": 1.8}])
    assert not _numpop_at(html, 0.3)["acik"], "hook segmentinde sayı popu görünüyor"
    assert not _numpop_at(html, 2.4)["acik"], "close segmentinde sayı popu görünüyor"
    beat = _numpop_at(html, 1.2)
    assert beat["acik"] and beat["metin"] == "240", "beat segmentinde sayı popu YOK"
