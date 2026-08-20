"""Arama niyeti: Trends'in "ilişkili aramaları" arasında SORU olanları ayırır.

NEDEN (2026-08-20, kullanıcı sorusu "trafiğin çoğu aramadan gelebilir"):
Trend konularında YouTube araması gerçekten şişer, ama iki farklı sorgu sınıfı var:

  1. Son dakika sorgusu ("istanbul deprem")  → SERP'te büyük yayıncılar ve
     YouTube'un haber rafı kazanır; küçük kanalın orada şansı yok.
  2. Soru sorgusu ("asgari ücrete zam gelecek mi", "adalar fayı nerede")
     → kimse 40 saniyelik CEVAP yayınlamıyor: gazete makale, TV canlı yayın
     veriyor. Küçük kanalın kazanabileceği dilim TAM OLARAK burası.

Elimizde bu sorguların BİREBİR metni zaten var (``NewsItem.trend_related``) ve
şimdiye kadar yalnız konu seçiminde kullanılıp atılıyordu. Bu modül onu iki yerde
kullanılabilir hale getirir:

  * metadata (başlık/açıklama/etiket) — YouTube'un metni sorguyla eşleştirebildiği
    TEK yer (bkz. youtube/metadata_writer.py),
  * seçim/sıralama — soru sorgusu taşıyan trendleri öne alma (bkz. scorer.py).

KONUŞULAN METNE DOKUNMAZ. Kullanıcının kuralı: arama verisi konuyu SEÇER,
seslendirmede ağza alınmaz (bkz. narration_writer.BANNED_PHRASES).
"""
from __future__ import annotations

from short_bot.text_normalize import locale_fold

# Soru sözcükleri — locale_fold edilmiş (aksansız) biçimde tutulur.
# Türkçe soru EKİ ayrı sözcük olarak yazılır ("gelecek mi"), bu yüzden token
# eşleşmesi yeter; "mi/mı/mu/mü" fold sonrası "mi"/"mu" olur.
_QUESTION_WORDS: dict[str, frozenset[str]] = {
    # DİKKAT: locale_fold aksan SÖKMEZ (yalnız Türkçe-doğru küçültme yapar), bu
    # yüzden işaretler gerçek Türkçe harfleriyle yazılır — "kac" hiçbir zaman
    # eşleşmez, "kaç" eşleşir.
    "tr": frozenset("""
mi mı mu mü midir mıdır mudur müdür miydi mıydı muydu müydü
ne nedir neden niçin niye nasıl nasıldır
kim kimdir kimin kime kimler kimdi
nerede nereye nereden neresi nerde hangi hangisi
kaç kaçta kaça kaçıncı kaçtı zaman
""".split()),
    "en": frozenset("what why how who when where which whose is are does do did can will".split()),
    "es": frozenset("que qué por cual cuál como cómo quien quién cuando cuándo donde dónde cuanto cuánto".split()),
    "de": frozenset("was warum wieso wie wer wann wo welche welcher wieviel".split()),
    "ja": frozenset("なぜ どこ いつ 誰 何 どう".split()),
}

# "ne zaman", "ne kadar" gibi iki sözcüklü kalıplar tek sözcükle karışmasın diye
# ayrıca aranır (tek başına "ne" zaten listede).
_QUESTION_PHRASES: dict[str, tuple[str, ...]] = {
    "tr": ("ne zaman", "ne kadar", "ne oldu", "ne demek", "kaç yaşında",
           "var mı", "gelecek mi", "olacak mı", "ne kadar oldu"),
    "en": ("how much", "how many", "what happened"),
    "es": ("cuanto cuesta", "que paso"),
    "de": ("wie viel", "was ist passiert"),
    "ja": (),
}


def _tokens(text: str) -> list[str]:
    return [locale_fold(t) for t in (text or "").split() if t]


def is_question_query(query: str, *, language: str = "tr") -> bool:
    """Bu arama dizesi bir SORU mu ("asgari ücrete zam gelecek mi")?

    Soru işareti aramaya yazılmaz; sinyal soru sözcüğü/ekidir.
    """
    q = (query or "").strip()
    if not q:
        return False
    if "?" in q:
        return True
    lang = (language or "tr").split("-")[0].lower()
    words = _QUESTION_WORDS.get(lang) or _QUESTION_WORDS["tr"]
    toks = _tokens(q)
    if set(toks) & words:
        return True
    folded = " ".join(toks)
    return any(p in folded for p in (_QUESTION_PHRASES.get(lang) or ()))


def question_queries(queries, *, language: str = "tr") -> list[str]:
    """Sorgular arasından yalnız SORU olanlar — geliş sırası korunur.

    Trends ilişkili aramaları zaten hacim sırasında gelir; sırayı bozmayız."""
    out: list[str] = []
    seen: set[str] = set()
    for q in queries or ():
        q = (q or "").strip()
        if not q:
            continue
        key = locale_fold(q)
        if key in seen:
            continue
        seen.add(key)
        if is_question_query(q, language=language):
            out.append(q)
    return out


def ranked_queries(queries, *, language: str = "tr", limit: int = 8,
                   questions_first: bool = False) -> list[str]:
    """Metadata'ya verilecek sorgu listesi. VARSAYILAN: Trends'in kendi sırası.

    NEDEN varsayılan "soru önce" DEĞİL: 2026-08-20'de ölçtük (Aslan Gündem,
    28 gün, YouTube Analytics arama terimleri). Bizi bulan ilk 25 sorgunun
    HİÇBİRİ soru değildi; hepsi varlık+niyet kalıbıydı:

        galatasaray (43K) · galatasaray transfer (25K) · gs transfer (14,6K)
        galatasaray transfer son dakika (5K) · gs çorum maç özeti (1,1K)

    Trends ilişkili aramaları zaten hacim sırasında gelir; onu bozmak ölçülen
    kazananı aşağı iter. ``questions_first=True`` yalnız SORU niyetli bir kanal
    (bkz. ChannelConfig.trends_intent="question") için anlamlıdır.

    UYARI (seçim yanlılığı): bu ölçüm yalnız BUGÜN sıralandığımız sorguları
    görebilir. Hiç soru-cevap videosu üretmediğimiz için "soru sorguları
    kazanılabilir mi" sorusu ölçülmüş DEĞİL, yanıtsız."""
    seen: set[str] = set()
    ordered: list[str] = []
    for q in queries or ():
        q = (q or "").strip()
        if not q:
            continue
        key = locale_fold(q)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(q)
    if questions_first:
        quest = [q for q in ordered if is_question_query(q, language=language)]
        rest = [q for q in ordered if not is_question_query(q, language=language)]
        ordered = quest + rest
    return ordered[:limit]


def item_queries(item) -> tuple[str, ...]:
    """NewsItem'ın ilişkili aramaları (Trends dışı kaynakta boş tuple)."""
    return tuple(getattr(item, "trend_related", ()) or ())


def has_question_intent(item, *, language: str = "tr") -> bool:
    """Bu trendin ilişkili aramalarında en az bir SORU var mı?"""
    return bool(question_queries(item_queries(item), language=language))


def intent_label(item, *, language: str = "tr") -> str:
    """Panelde gösterilecek rozet: 'soru' | 'son dakika' | ''(trend değil)."""
    if not item_queries(item):
        return ""
    return "soru" if has_question_intent(item, language=language) else "son dakika"
