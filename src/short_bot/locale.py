"""Locale dictionaries: RSS URL hints + UI labels + prompt language names.

Multi-language support for short-bot. Each language maps to:
- An RSS URL fragment (hl/gl/ceid params for Google News)
- A human-readable language name (used in LLM prompts)
- A small UI vocabulary (BEĞEN/SUBSCRIBE/SHARE/BREAKING)
"""
from __future__ import annotations

SUPPORTED_LANGUAGES = ["tr", "en", "de", "es", "fr", "ja"]


RSS_LOCALES: dict[str, str] = {
    "tr": "hl=tr&gl=TR&ceid=TR:tr",
    "en": "hl=en-US&gl=US&ceid=US:en",
    "de": "hl=de&gl=DE&ceid=DE:de",
    "es": "hl=es&gl=ES&ceid=ES:es",
    "fr": "hl=fr&gl=FR&ceid=FR:fr",
    "ja": "hl=ja&gl=JP&ceid=JP:ja",
}


LANGUAGE_NAMES: dict[str, str] = {
    "tr": "Türkçe",
    "en": "English",
    "de": "Deutsch",
    "es": "Español",
    "fr": "Français",
    "ja": "日本語",
}


# ISO 3166-1 alpha-2 region codes for Google Trends / YouTube Trending.
# YouTube uses `regionCode`; Google Trends uses `geo` — both accept the same codes.
TREND_REGIONS: dict[str, str] = {
    "tr": "TR",
    "en": "US",
    "de": "DE",
    "es": "ES",
    "fr": "FR",
    "ja": "JP",
}


def trend_region_for(language: str) -> str:
    """Return the ISO region code used by Google Trends/YouTube Trending APIs."""
    return TREND_REGIONS[language]


# like/subscribe/share etiketleri KALDIRILDI (2026-07-16, kullanıcı kararı):
# ekranda hiçbir beğeni/abone öğesi kalmadı.
UI_LABELS: dict[str, dict[str, str]] = {
    "tr": {"breaking": "SON DAKİKA",     "source": "Kaynak"},
    "en": {"breaking": "BREAKING",        "source": "Source"},
    "de": {"breaking": "EILMELDUNG",      "source": "Quelle"},
    "es": {"breaking": "ÚLTIMA HORA",     "source": "Fuente"},
    "fr": {"breaking": "DERNIÈRE MINUTE", "source": "Source"},
    "ja": {"breaking": "速報",             "source": "出典"},
}


def rss_locale_for(language: str) -> str:
    """Return the Google News RSS URL fragment for `language`. Raises KeyError if unknown."""
    return RSS_LOCALES[language]


def ui_labels_for(language: str) -> dict[str, str]:
    """Return the UI label dict for `language`. Raises KeyError if unknown."""
    return UI_LABELS[language]


def language_name(language: str) -> str:
    """Return the human-readable language name (e.g. 'Türkçe' for 'tr'). Raises KeyError."""
    return LANGUAGE_NAMES[language]


# Dilin alfabesindeki ASCII-DIŞI harfler. Aksan temizleyicisi
# (text_normalize.strip_foreign_diacritics) bu tabloda OLMAYAN her aksanı söker.
#
# NEDEN OLGU TABLOSU, NEDEN DİL PAKETİNDE DEĞİL: alfabe bir olgudur, üslup değil.
# Dil paketini Sonnet üretiyor; 'ß'i unutursa Almanca anlatım metni SESSİZCE bozulur
# ("Weiß" → "Wei") ve bunu hiçbir hata bildirmez. Bu riski almanın karşılığı yok.
ALPHABET_EXTRA: dict[str, str] = {
    "tr": "ÇĞİıÖŞÜçğöşü",
    "en": "",
    "de": "ÄÖÜäöüß",
    "es": "ÑñÁÉÍÓÚÜáéíóúü¿¡",
    "fr": "ÀÂÆÇÉÈÊËÎÏÔŒÙÛÜŸàâæçéèêëîïôœùûüÿ",
    # Japonca BOŞ ve olması gereken bu: kana/kanji'yi tablo değil, blok kuralı korur
    # (text_normalize._CJK_START — 50.000 kanji tabloya yazılamaz). Buradaki boşluk
    # yalnız "metne sızan LATİN aksanı sökülsün" demek.
    "ja": "",
}


# Boşluksuz yazan ve KENDİ GLİF KÜMESİNİ isteyen diller.
CJK_LANGUAGES = frozenset({"ja", "zh"})

# CJK glifi TAŞIYAN fontlar. Kanalın 7 marka fontunun (Montserrat/Anton/Bebas Neue/
# Oswald/Poppins/Inter/Archivo Black) hiçbirinde kana/kanji YOK: Japonca kanal onlardan
# biriyle kurulursa ekrana tofu (□□□) basar ya da sessizce sistem fontuna düşer — yani
# kanalın kimliği olan font hiç uygulanmaz ve bunu hiçbir hata bildirmez.
#
# Adlar reel_render._FONT_IMPORTS anahtarlarıyla BİREBİR olmalı (test bunu bağlar);
# ayrışırsa render yine sessizce Montserrat'a düşer.
CJK_FONTS: dict[str, tuple[str, ...]] = {
    "ja": ("Noto Sans JP",),
    "zh": ("Noto Sans JP",),
}


def font_supports_language(font: str, language: str) -> bool:
    """``font`` bu dilin harflerini basabilir mi? CJK dışı dillerde her font geçerli."""
    if language not in CJK_LANGUAGES:
        return True
    return font in CJK_FONTS.get(language, ())


# Dile ÖZGÜ anlatım kuralları — ÜSLUP TERCİHİ DEĞİL, DİL OLGUSU. Prompt'a eklenir.
#
# NEDEN OLGU TABLOSU, NEDEN DİL PAKETİNDE DEĞİL: paketi Sonnet üretiyor; 'kayıt
# tutarlılığı' gibi bir kuralı unutursa anlatım SESSİZCE bozulur (ALPHABET_EXTRA ile
# aynı gerekçe).
#
# CANLI KANIT: yerli okur kapısı ilk Japonca denemeyi reddetti — hook sade biçimde
# ("一人だった"), beat'ler nazik biçimde ("走り出しました"). Yerli kulağa bozuk gelir.
# Kapı yakalıyor ama yakalamak pahalı (fazladan Sonnet turu, bazen klip kaybı);
# kuralı yazarın önüne koymak bedava.
NARRATION_STYLE_RULES: dict[str, str] = {
    # Bu liste TEK TEK ÜRETİM HATALARINDAN çıkarıldı (2026-07-24): her maddeyi bir yerli
    # okur reddi doğurdu ve her biri KLİP MALİYETİNE mal oldu. Beşi de "makine yazımı
    # Japonca"nın klasik işaretleri; modele önden söylemek reddi ucuzlatıyor.
    "ja": (
        "JAPANESE NARRATION SPEC — a native listener spots each of these instantly:\n"
        "  1) REGISTER: ONE politeness level for the WHOLE script, polite です・ます. "
        "Never mix plain form (だった / した / ある) with polite form (でした / しました / "
        "あります). This applies to the hook and to the closing CTA as well — dropping "
        "into casual 〜てね at the end is the same error.\n"
        "  2) TENSE: pick ONE and hold it. Tell the story in past tense (〜ました / "
        "〜でした). Do NOT drift between past and present sentence by sentence "
        "(ためらいませんでした → 運び続けます → 足を止めませんでした); random drift is a "
        "translation tell. One deliberate present-tense sentence for emphasis is fine.\n"
        "  3) SENTENCE JOINS: no comma splices. 「子猫が弱っていました、母猫は…」 is wrong — "
        "use two sentences or join with the て-form.\n"
        "  4) COLLOCATIONS: use the verb Japanese actually pairs with the noun. "
        "支える is for holding up a STRUCTURE, not for a cat staying beside its kitten "
        "(寄り添う). 息 is not 繰り返す'd (息を切らす).\n"
        "  4b) THE CTA HAS A FIXED SHAPE — TWO sentences, in this order:\n"
        "        (i)  a QUESTION to the viewer about what was just shown, ending in か。 "
        "— 「この優しさ、どう感じましたか。」「あなたならどうしますか。」\n"
        "        (ii) 「コメントで教えてください。」\n"
        "      A bare コメントで教えてください with no question before it is REJECTED every "
        "time: it is a direct calque of \"let us know in the comments\", the viewer is "
        "never told what to say, and the voice jumps from third-person storytelling to "
        "addressing the audience with no bridge. A statement (…でした。) does not count as "
        "the bridge — it must be a QUESTION. Both sentences in です・ます.\n"
        "      Do NOT write a like/heart-button CTA: every phrasing is contested "
        "(ハートを残す is a literal translation and plainly wrong; ハートを押す, "
        "ハートボタンを押す and ハートマークをタップ are each rejected by some native "
        "readers), so it costs a repair round and buys nothing.\n"
        "  5) SPOKEN, NOT LITERARY: no である / であります, no stiff connectives "
        "(しかしながら / 〜ゆえに), no redundant padding (荒い息を繰り返す → 息を切らす).\n"
        "  6) ON-SCREEN LENGTH: Japanese glyphs are FULL-WIDTH (1em each), Latin letters "
        "average about half that, so the generic limits are far too loose here.\n"
        "     • \"cover_title\": at most 6 characters. It is drawn at 140px in a 960px "
        "box — that is 960/140 ≈ 6.8 full-width glyphs per line, so 7+ characters wrap "
        "onto a second line and overflow (observed: 母の愛、離さない). 母の愛 / "
        "決して忘れない are the right size.\n"
        "     • \"close\": at most 25 characters INCLUDING the comment CTA. It is drawn "
        "at 104px in the same 960px box ≈ 9 full-width glyphs per line, so 40+ characters "
        "become a four-line wall that auto-shrinks to tiny text and freezes over the "
        "payoff shot (observed twice on real videos). 25 is enough: "
        "「母の愛は本物でした。コメントで教えてください。」is 22."
    ),
}


def narration_style_rule(language: str) -> str:
    """Bu dile özgü anlatım kuralı; tanımlı değilse boş (prompt uzamasın)."""
    return NARRATION_STYLE_RULES.get(language, "")


def default_font_for(language: str) -> str | None:
    """Bu dil için zorunlu/varsayılan font; CJK dışı dillerde None (kanal kendi seçer)."""
    fonts = CJK_FONTS.get(language) if language in CJK_LANGUAGES else None
    return fonts[0] if fonts else None
