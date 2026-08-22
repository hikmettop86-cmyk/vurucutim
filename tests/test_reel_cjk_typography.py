"""CJK altyazı tipografisi — öksüz satır ve öbek-ortası kırılma yasak.

GERÇEK KUSUR (Japonca deneme videosu, 2026-07-24): altyazı bloğu Türkçe için kurulmuş
kırma kurallarıyla akıyordu ve Japoncada iki şey bozuluyordu:

  • ÖBEK ORTASINDAN kırılma — "降りてきてしゃ / がみました。" Vurgulanan karaoke birimi
    iki satıra bölünüyor; sarı vurgu satır atlıyor. (Japonca satır sonu HER karakterden
    olabilir, o yüzden tarayıcı bunu seve seve yapar.)
  • ÖKSÜZ SATIR — "…コメントに❤を残してくだ / さい。" son satırda 3 karakter kalıyor.

Birincisi dile bakmaksızın yanlış: vurgulanan bir birim asla bölünmemeli. İkincisi
CJK'ye özgü (禁則処理) ve YALNIZ CJK'de uygulanmalı — Türkçe kanalların kanıtlanmış
görünümü değişmemeli.
"""
from short_bot.reel_models import (ReelBeat, ReelNarration, TimedWord,
                                   build_reel_timeline)
from short_bot.reel_render import build_reel_overlay_html
from short_bot.text_normalize import language


def _tl_tr():
    n = ReelNarration(
        hook="Bal nasıl olur?",
        beats=[ReelBeat(text="Arılar nektar toplar burada.", visual_query="bee"),
               ReelBeat(text="Enzimlerle işler bunu.", visual_query="bee macro"),
               ReelBeat(text="Peteğe biriktirir hemen.", visual_query="honeycomb")],
        close="İşte arının emeği.", mood="upbeat")
    asr = [TimedWord(word=w, start_s=float(i), end_s=float(i + 1), seg=-1)
           for i, w in enumerate(n.full_text().split())]
    return build_reel_timeline(n, asr, duration_s=float(len(asr)))


def _tl_ja():
    with language("ja"):
        n = ReelNarration(
            hook="病院の廊下、たった一人の男の子",
            beats=[ReelBeat(text="椅子で静かに待っていました。", visual_query="clip"),
                   ReelBeat(text="窓辺のスパイダーマンに両手を広げました。", visual_query="clip"),
                   ReelBeat(text="そのまま胸に抱き上げられました。", visual_query="clip")],
            close="胸に響いたら、コメントに残してください。",
            mood="calm")
        return build_reel_timeline(n, [], duration_s=30.0)


def test_highlight_unit_never_splits_across_lines():
    """Vurgulanan karaoke birimi bölünemez — her dilde geçerli."""
    import re
    html = build_reel_overlay_html(_tl_ja(), lang="ja")
    m = re.search(r"\.cap\s+\.w\{([^}]*)\}", html)
    assert m, "'.cap .w' kuralı bulunamadı"
    assert "nowrap" in m.group(1), m.group(1)


def test_cjk_rules_applied_for_japanese():
    html = build_reel_overlay_html(_tl_ja(), lang="ja")
    assert "line-break:strict" in html.replace(" ", "")
    assert "text-wrap:balance" in html.replace(" ", "")


def test_cjk_rules_absent_for_turkish():
    """Türkçe kanalların KANITLANMIŞ görünümü değişmesin."""
    html = build_reel_overlay_html(_tl_tr(), lang="tr")
    flat = html.replace(" ", "")
    assert "line-break:strict" not in flat
    assert "text-wrap:balance" not in flat


def test_japanese_captions_render_actual_text():
    html = build_reel_overlay_html(_tl_ja(), lang="ja")
    assert "病院" in html
