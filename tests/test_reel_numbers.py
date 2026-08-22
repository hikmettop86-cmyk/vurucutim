from short_bot.reel_models import TimedWord
from short_bot.reel_numbers import MAX_POPS, find_numbers


def _w(text, i, seg=1):
    return TimedWord(word=text, start_s=float(i), end_s=float(i) + 0.5, seg=seg)


def test_finds_plain_number_and_percent():
    words = [_w("Beyni", 0), _w("240", 1), _w("parçaya", 2), _w("bölündü", 3),
             _w("ve", 4), _w("%90", 5), _w("kayboldu", 6)]
    hits = find_numbers(words)
    texts = [h["text"] for h in hits]
    assert "240 parçaya" in texts
    assert "%90" in texts


def test_merges_multiplier_unit():
    words = [_w("Tam", 0), _w("24", 1), _w("milyon", 2), _w("kişi", 3)]
    hits = find_numbers(words)
    assert hits and hits[0]["text"] == "24 milyon"
    # start_s SAYININ kelimesinden gelir (birim birleşince kaymamalı)
    assert hits[0]["start_s"] == 1.0 and hits[0]["end_s"] == 2.5
    assert hits[0]["word_index"] == 1


def test_ignores_written_out_numbers():
    words = [_w("bir", 0), _w("iki", 1), _w("üç", 2), _w("kelime", 3)]
    assert find_numbers(words) == []


def test_caps_at_max_pops_keeping_biggest():
    words = [_w(str(v), i) for i, v in enumerate([5, 10, 1000, 24, 999999, 3, 77])]
    hits = find_numbers(words)
    assert len(hits) <= MAX_POPS
    vals = [h["text"] for h in hits]
    assert "999999" in vals and "1000" in vals      # en büyükler tutuldu
    # zaman sırası korunur (overlay sırayla gösterecek)
    assert hits == sorted(hits, key=lambda h: h["start_s"])
