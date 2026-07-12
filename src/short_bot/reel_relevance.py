"""Footage off-topic tespiti: vision-tarifi ↔ senaryo konu-havuzu token-overlap.

faceless-2 `src/footage-relevance-core.js` portu. Domain bilgisi YOK — genel
morfoloji + stopword. Vision'ın gevşek evet/hayır yargısı yerine deterministik
kelime örtüşmesi: klibin GÖRDÜĞÜ (vision-description) kelimeler senaryonun konu
dağarcığında karşılık buluyor mu.
"""
from __future__ import annotations

import re

# Genel EN stopword + görsel-jenerik + jenerik özne/fiil/renk/boyut/mekan/ortam.
# Konu sinyali TAŞIMAYAN kelimeler (whale/ocean/lawn/mower gibi konu kelimeleri YOK).
STOPWORDS = frozenset("""
a an the and or but of in on at to for with as is are was were be been being it
its this that these those you your they their them we our us he she his her from
by about into onto over under after before than then so if not no can will would
could should may might must just what which who whom when where why how all any
some one two more most many much very out up down off has have had do does did
because while during each every both few other such only own same also still even
here there now
close closeup shot view image images photo photograph footage clip video scene
background foreground camera frame screen angle wide picture visible showing shows
depicts depicting featuring
man men woman women person people guy hand hands sits sit sitting holds hold
holding uses use using stands stand standing works work working operates operate
operating pushes push pushing pulls pull pulling moves move moving seen wearing wears
red green blue yellow black white orange brown silver gray grey dark bright light
large small area field side floor room space surface various outdoor setting sunny
near well morning afternoon evening weather cloudy lot nearby across along around
through between above below grassy park day hour moment time
""".split())

MIN_POOL = 6


def extract_topic_words(*texts) -> set[str]:
    """lowercase, [a-z]+ eşleşmeleri, len>=3 ve stopword-dışı benzersiz kelimeler."""
    words: set[str] = set()
    for t in texts:
        if not t:
            continue
        for w in re.findall(r"[a-z]+", str(t).lower()):
            if len(w) >= 3 and w not in STOPWORDS:
                words.add(w)
    return words


def overlap_ratio(words_a: set[str], words_b: set[str]) -> float:
    """words_a'daki kelimelerin words_b'de bulunma oranı (0..1). a boşsa 1.0."""
    if not words_a:
        return 1.0
    hit = sum(1 for w in words_a if w in words_b)
    return hit / len(words_a)


def _add_plurals(pool: set[str]) -> set[str]:
    """Her kelimenin tekil↔çoğul eşini ekle (morfolojik genel kural)."""
    for w in list(pool):
        if w.endswith("s") and len(w) > 3:
            pool.add(w[:-1])
        else:
            pool.add(w + "s")
    return pool


def build_topic_pool(visual_queries, anchor: str = "", extra_texts=(),
                     min_beat_freq: int = 2) -> "set[str] | None":
    """Anchor-baskın konu havuzu: çıpa kelimeleri + ≥min_beat_freq tekrar eden
    beat kelimeleri. Tek-seferlik YUMUŞAK kelimeler ('baby', 'tropical') havuza
    GİRMEZ — aksi hâlde 'baby whale' sorgusu havuza 'baby' sokup insan-bebeği
    footage'ını (ratio~0.33) geçirirdi. Domain kelimeleri (whale/ocean) yüksek-
    isabetli sinyaldir; footage-sürüklü kanalda emin olunmayan beat güvenle çıpaya
    düşer (faceless-2 buildTopicPool minFreq=2 + otoriter-alan mantığı).

    ``anchor`` boş + havuz MIN_POOL altı → None (zayıf, çıpasız havuzla over-fire
    yerine gate pasif). ``anchor`` varsa küçük havuz bile kullanılır (yüksek isabet).
    """
    anchor_words = extract_topic_words(anchor)
    freq: dict[str, int] = {}
    for q in (visual_queries or []):
        for w in extract_topic_words(q):
            freq[w] = freq.get(w, 0) + 1
    recurring = {w for w, c in freq.items() if c >= min_beat_freq}
    pool: set[str] = set(anchor_words) | recurring
    for t in (extra_texts or ()):
        pool |= extract_topic_words(t)
    if not pool:
        return None
    if not anchor_words and len(pool) < MIN_POOL:
        return None
    return _add_plurals(pool)


def analyze_scene(description: str, pool, min_hits: int = 1) -> dict:
    """Vision-tarifini anchor-baskın havuza vur: off_topic = domain kelimesi YOK.

    Havuz yüksek-isabetli (anchor + tekrar edenler) olduğundan karar ORAN değil
    İSABET-SAYISI temellidir: tarif en az ``min_hits`` domain kelimesi içermeli.
    Uzunluğa duyarsız — insan-bebeği/tatil-plajı (0 isabet) off; iceberg 'ocean'
    (1 isabet, oran~0.17) on-topic KALIR (kutup besleme alanı balina konusunda).

    description boş → no-vision (pasif); pool boş/None → no-topic (pasif).
    """
    desc_words = extract_topic_words(description)
    if not desc_words:
        return {"off_topic": False, "ratio": None, "hits": 0, "reason": "no-vision"}
    if not pool:
        return {"off_topic": False, "ratio": None, "hits": 0, "reason": "no-topic"}
    hits = sum(1 for w in desc_words if w in pool)
    ratio = hits / len(desc_words)
    off = hits < min_hits
    return {"off_topic": off, "ratio": ratio, "hits": hits,
            "reason": "off-topic" if off else "ok"}


def derive_footage_anchor(search_query_template: str) -> str:
    """dna.search_query_template'ten İngilizce literal çıpayı türet.

    '{header_top} {header_bottom} whale ocean' → 'whale ocean'. {placeholder}'lar
    ve <3 harf kelimeler atılır; sıra korunur, tekrar elenir.
    """
    if not search_query_template:
        return ""
    stripped = re.sub(r"\{[^}]*\}", " ", str(search_query_template))
    out: list[str] = []
    for w in re.findall(r"[a-z]+", stripped.lower()):
        if len(w) >= 3 and w not in out:
            out.append(w)
    return " ".join(out)
