"""Marker konumu ALT-KESİM başına ölçülmeli, segment başına değil.

GERÇEK HATA (arı videosu): kırmızı marker'lar bazen boşluğu işaretliyordu.

Kök neden: ``locate_subject`` segmentin İLK klibinden (got[0]) konum çıkarıyor, ama
hızlı kesim açıkken o segmentte 3 FARKLI klip gösteriliyordu. Marker A klibindeki
arının konumuna göre yerleştirilip B ve C kliplerinin üstünde de çiziliyordu.
Üstelik kare klibin sabit 1. saniyesinden alınıyordu, oysa alt-kesim başka bir
saniyeden başlıyor ve özne (uçan arı) o arada yer değiştiriyor.
"""
from short_bot.footage_matcher import SubjectPos
from short_bot.reel_markers import build_markers


def _pos(found=True, discrete=True, conf=0.9, x=0.5, y=0.5):
    return SubjectPos(found=found, discrete=discrete, confidence=conf, x=x, y=y)


# subcuts: (segment_index, t0, t1)
SUBCUTS = [
    (0, 0.0, 3.0),      # hook
    (1, 3.0, 5.0),      # beat 1 — klip A
    (1, 5.0, 7.0),      # beat 1 — klip B
    (2, 7.0, 9.0),      # beat 2 — klip C
    (3, 9.0, 12.0),     # kapanış
]


def test_marker_is_bound_to_the_subcut_it_was_measured_on():
    """Marker YALNIZ ölçüldüğü alt-kesim süresince görünür.

    Eskiden segment 1 boyunca (3.0-7.0) çiziliyordu — ama 5.0'da klip değişiyor,
    yani marker'ın son 2 saniyesi BAŞKA bir klibin üstündeydi.
    """
    positions = [_pos(found=False),           # hook: konum yok
                 _pos(conf=0.9, x=0.3, y=0.4),  # klip A: arı burada
                 _pos(conf=0.9, x=0.8, y=0.7),  # klip B: arı BAŞKA yerde
                 _pos(found=False),
                 _pos(found=False)]
    mk = build_markers(SUBCUTS, positions, marker_kit=("ring",), frequency="beats")
    assert mk, "marker üretilmedi"
    m = mk[0]
    assert m["t0"] == 3.0 and m["t1"] == 5.0     # klip A'nın penceresi
    assert (m["x"], m["y"]) == (0.3, 0.4)        # klip A'da ölçülen konum
    # Marker klip B'nin penceresine TAŞMAZ
    assert all(not (x["t0"] <= 5.5 < x["t1"] and x["x"] == 0.3) for x in mk)


def test_one_marker_per_segment_at_most():
    """Her alt-kesime marker koymak görsel gürültü olur — segment başına EN İYİSİ."""
    positions = [_pos(found=False),
                 _pos(conf=0.6, x=0.3, y=0.3),
                 _pos(conf=0.95, x=0.8, y=0.8),   # daha güvenli olan seçilmeli
                 _pos(found=False),
                 _pos(found=False)]
    mk = build_markers(SUBCUTS, positions, marker_kit=("ring",), frequency="beats")
    segs = [m["seg"] for m in mk]
    assert len(segs) == len(set(segs)), "bir segmentte birden fazla marker"
    assert mk[0]["t0"] == 5.0 and (mk[0]["x"], mk[0]["y"]) == (0.8, 0.8)


def test_low_confidence_and_non_discrete_get_no_marker():
    """Manzara/dağınık sahnede marker ÇIKMAZ — boşluğu işaretlemektense hiç olmasın."""
    positions = [_pos(found=False),
                 _pos(discrete=False, conf=0.99),   # manzara
                 _pos(conf=0.2),                    # emin değil
                 _pos(found=False),
                 _pos(found=False)]
    assert build_markers(SUBCUTS, positions, marker_kit=("ring",),
                         frequency="beats") == []


def test_frequency_off_disables_markers():
    positions = [_pos()] * len(SUBCUTS)
    assert build_markers(SUBCUTS, positions, marker_kit=("ring",),
                         frequency="off") == []


def test_hook_and_close_never_get_markers():
    """Hook/kapanış kartı ekranı kaplar; marker altında kalır ve kirletir."""
    positions = [_pos(conf=0.99)] * len(SUBCUTS)
    mk = build_markers(SUBCUTS, positions, marker_kit=("ring",), frequency="beats")
    assert all(m["seg"] not in (0, 3) for m in mk)
