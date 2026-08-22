"""CJK dilli kanal, CJK glifi OLMAYAN bir fontla kurulamaz.

GERÇEK TUZAK: kanalın 7 marka fontunun (Montserrat/Anton/Bebas/Oswald/Poppins/Inter/
Archivo Black) HİÇBİRİNDE kana/kanji glifi yok. Japonca kanal bunlardan biriyle
kurulursa ekrana tofu (□□□) basar ya da sessizce sistem fontuna düşer — yani kanalın
KİMLİĞİ olan font hiç uygulanmaz. Hata yok, log yok.

Panelden kürate kanalı kurarken font HİÇ set edilmiyordu (ReelConfig varsayılanı
Montserrat), yani "Japonca" seçmek tek başına bozuk bir kanal üretiyordu.
"""
import pytest

from short_bot.locale import (CJK_LANGUAGES, default_font_for,
                              font_supports_language)


def test_turkish_accepts_any_brand_font():
    for f in ("Montserrat", "Anton", "Bebas Neue", "Noto Sans JP"):
        assert font_supports_language(f, "tr")


def test_japanese_rejects_latin_only_fonts():
    for f in ("Montserrat", "Anton", "Bebas Neue", "Oswald", "Poppins",
              "Inter", "Archivo Black"):
        assert not font_supports_language(f, "ja"), f


def test_japanese_accepts_cjk_font():
    assert font_supports_language("Noto Sans JP", "ja")


def test_default_font_for_japanese_is_cjk_capable():
    f = default_font_for("ja")
    assert f is not None and font_supports_language(f, "ja")


def test_default_font_for_turkish_is_none():
    """Türkçede zorlama yok — kanal kendi markasını seçer."""
    assert default_font_for("tr") is None


def test_every_cjk_language_has_a_default_font():
    for lang in CJK_LANGUAGES:
        assert default_font_for(lang), lang


def test_declared_cjk_fonts_exist_in_the_render_table():
    """locale'deki font adı reel_render._FONT_IMPORTS'ta YOKSA render sessizce
    Montserrat'a düşer — iki tablo ayrışmasın."""
    from short_bot.reel_render import _FONT_IMPORTS
    for lang in CJK_LANGUAGES:
        assert default_font_for(lang) in _FONT_IMPORTS


# --------------------------------------------------------------- kanal yükleme kapısı

_BASE = (
    "slug: t1\nname: T\nkeywords: []\nlanguage: ja\nschedule_cron: 0 12 * * *\n"
    "duration_s: 20\nmin_score: 7.0\nmax_candidates_per_run: 3\nmax_age_hours: 24\n"
    "template: newscast\n"
    "colors: {primary: '#ec4899', accent: '#f9a8d4', bg_gradient: ['#000','#111']}\n"
    "handle: '@t1'\noutput_dir: output/t1\nenabled: false\ncontent_source: curated\n"
    "reel:\n  enabled: true\n  voice_id: v1\n  curated_tone: duygu\n  font: __FONT__\n"
)


def _yaml(*, font):
    # .format() KULLANMA: gövdedeki YAML akış eşlemesi ({primary: ...}) format'ı kırar.
    return _BASE.replace("__FONT__", font)


def test_load_channel_rejects_japanese_with_latin_font(tmp_path):
    p = tmp_path / "t1.yaml"
    p.write_text(_yaml(font="Montserrat"), encoding="utf-8")
    from short_bot.config import load_channel
    with pytest.raises(ValueError, match="font"):
        load_channel(p)


def test_load_channel_accepts_japanese_with_cjk_font(tmp_path):
    p = tmp_path / "t1.yaml"
    p.write_text(_yaml(font="Noto Sans JP"), encoding="utf-8")
    from short_bot.config import load_channel
    assert load_channel(p).reel.font == "Noto Sans JP"


def test_load_channel_ignores_font_when_reel_disabled(tmp_path):
    """Reel kapalıysa font hiç kullanılmıyor — kanalı yüklenemez yapma."""
    p = tmp_path / "t1.yaml"
    p.write_text(_yaml(font="Montserrat").replace(
        "reel:\n  enabled: true", "reel:\n  enabled: false"), encoding="utf-8")
    from short_bot.config import load_channel
    assert load_channel(p).language == "ja"


def test_turkish_channel_with_any_font_still_loads(tmp_path):
    p = tmp_path / "t1.yaml"
    p.write_text(_yaml(font="Anton").replace("language: ja", "language: tr"),
                 encoding="utf-8")
    from short_bot.config import load_channel
    assert load_channel(p).reel.font == "Anton"


# --- DNA fontları da denetlenmeli ---------------------------------------------

def test_dna_fontu_da_cjk_kapisindan_gecer(tmp_path):
    """BOŞLUK (2026-08-22, Japonca kanal kurulurken): kapı yalnız `reel.font`'a
    bakıyordu. Trend/yorum kanalları reel KULLANMAZ, `dna.fonts` kullanır —
    Latin fontlu bir Japonca DNA sessizce tofu basardı, tam da bu kapının
    kurulma sebebi."""
    import yaml
    from short_bot.config import load_channel

    data = {
        "slug": "ja-test", "name": "テスト", "keywords": ["a"], "language": "ja",
        "schedule_cron": "0 9 * * *", "duration_s": 6, "min_score": 6.0,
        "max_candidates_per_run": 10, "max_age_hours": 24, "template": "flas",
        "colors": {"primary": "#d0021b", "accent": "#ffe600",
                   "bg_gradient": ["#111111", "#222222"]},
        "handle": "@t", "output_dir": "o", "enabled": False,
        "dna": {
            "archetype": "flas",
            "palette": {"primary": "#d0021b", "accent": "#ffe600",
                        "bg_gradient": ["#111111", "#222222"],
                        "body_bg": ["#111111", "#0e0e0e"],
                        "text_main": "#ececec", "text_muted": "#9a9a9a"},
            "fonts": {"headline": "Oswald", "body": "Barlow"},   # CJK glifi YOK
            "tone": {"voice": "v", "style": "s"},
            "persona_summary": "özet",
        },
    }
    p = tmp_path / "ja-test.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="tofu|CJK"):
        load_channel(p)


def test_cjk_fontlu_dna_kabul_edilir(tmp_path):
    import yaml
    from short_bot.config import load_channel

    data = {
        "slug": "ja-ok", "name": "テスト", "keywords": ["a"], "language": "ja",
        "schedule_cron": "0 9 * * *", "duration_s": 6, "min_score": 6.0,
        "max_candidates_per_run": 10, "max_age_hours": 24, "template": "flas",
        "colors": {"primary": "#d0021b", "accent": "#ffe600",
                   "bg_gradient": ["#111111", "#222222"]},
        "handle": "@t", "output_dir": "o", "enabled": False,
        "dna": {
            "archetype": "flas",
            "palette": {"primary": "#d0021b", "accent": "#ffe600",
                        "bg_gradient": ["#111111", "#222222"],
                        "body_bg": ["#111111", "#0e0e0e"],
                        "text_main": "#ececec", "text_muted": "#9a9a9a"},
            "fonts": {"headline": "Noto Sans JP", "body": "Noto Sans JP"},
            "tone": {"voice": "v", "style": "s"},
            "persona_summary": "özet",
        },
    }
    p = tmp_path / "ja-ok.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert load_channel(p).dna.fonts.headline == "Noto Sans JP"
