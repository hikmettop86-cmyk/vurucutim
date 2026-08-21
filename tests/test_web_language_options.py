"""Panelden kaydetmek kanalın DİLİNİ/TONUNU sessizce değiştirmemeli.

İKİ AYRI SESSİZ SIFIRLAMA, ikisi de aynı sınıftan:

1) Dil açılırı elle yazılmıştı ve 'ja' yoktu. Hiçbir option `selected` olmayınca
   tarayıcı İLKİNİ (Türkçe) seçer; operatör o sayfada ilgisiz bir ayarı değiştirip
   kaydettiğinde kanalın dili TÜRKÇE olurdu — sonraki üretim Japonca ses ve Japonca
   fontla TÜRKÇE anlatım basardı. (Japonca kanal kurulurken yakalandı.)

2) Kürate kaydedicisi tonu ``"duygu" if form=="duygu" else "mizah"`` diye okuyordu.
   Açılırda KARMA seçeneği var ama kaydedici onu MİZAH'a çeviriyordu: karmadayi
   kanalının YAML'ında bugün `curated_tone: mizah` yazmasının sebebi bu.

Açılırlar tek kaynaktan (SUPPORTED_LANGUAGES) türetilmeli, kaydediciler de gerçekten
gelen değeri yazmalı — yoksa bir sonraki dil/ton eklendiğinde aynı tuzak geri gelir.
"""
import pytest

from short_bot.locale import SUPPORTED_LANGUAGES
from short_bot.web import create_app

_SETTINGS = (
    "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
    "web: {host: 127.0.0.1, port: 5005}\n"
    "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
    "claude_models:\n  dna: opus\n  default: haiku\n"
)


def _channel_yaml(*, slug, language, source, tone="duygu", font="Noto Sans JP"):
    kw = "[haber]" if source == "rss" else "[]"      # rss kanalı keyword'süz yüklenmez
    return (
        f"slug: {slug}\nname: {slug}\nkeywords: {kw}\nlanguage: {language}\n"
        f"schedule_cron: 0 12 * * *\nduration_s: 20\nmin_score: 7.0\n"
        f"max_candidates_per_run: 3\nmax_age_hours: 24\ntemplate: newscast\n"
        f"colors: {{primary: '#ec4899', accent: '#f9a8d4', bg_gradient: ['#000','#111']}}\n"
        f"handle: '@{slug}'\noutput_dir: output/{slug}\nenabled: false\n"
        f"content_source: {source}\n"
        f"reel:\n  enabled: true\n  voice_id: v1\n  font: {font}\n"
        f"  curated_tone: {tone}\n"
    )


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(_SETTINGS, encoding="utf-8")
    # reel kanalı (edit-reel sayfasını görür) + kürate kanalı (edit-curated'a yönlenir)
    (cfg_dir / "channels" / "jareel.yaml").write_text(
        _channel_yaml(slug="jareel", language="ja", source="rss"), encoding="utf-8")
    (cfg_dir / "channels" / "jakurate.yaml").write_text(
        _channel_yaml(slug="jakurate", language="ja", source="curated", tone="karma"),
        encoding="utf-8")
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      scheduler=False)


# ------------------------------------------------------------------ dil açılırları

def test_reel_edit_offers_every_supported_language(app):
    body = app.test_client().get("/channels/jareel/edit-reel").data.decode("utf-8")
    for lang in SUPPORTED_LANGUAGES:
        assert f'value="{lang}"' in body, f"'{lang}' dil açılırında yok"


def test_reel_edit_preselects_the_channel_language(app):
    """Seçili işareti yoksa tarayıcı İLK seçeneği alır → kaydet = dili değiştir."""
    import re
    body = app.test_client().get("/channels/jareel/edit-reel").data.decode("utf-8")
    m = re.search(r'<option value="ja"[^>]*>', body)
    assert m, "'ja' seçeneği yok"
    assert "selected" in m.group(0), m.group(0)


def test_new_channel_form_offers_every_supported_language(app):
    body = app.test_client().get("/channels/new").data.decode("utf-8")
    for lang in SUPPORTED_LANGUAGES:
        assert f'value="{lang}"' in body, f"'{lang}' yeni-kanal açılırında yok"


def test_new_curated_form_offers_every_supported_language(app):
    """Kürate kanalı yalnız Türkçe kurulabiliyordu — Japonca kanal panelden açılamazdı."""
    body = app.test_client().get("/channels/new-curated").data.decode("utf-8")
    for lang in SUPPORTED_LANGUAGES:
        assert f'value="{lang}"' in body, f"'{lang}' yeni-kürate açılırında yok"


# ------------------------------------------------- kürate kaydı bir şey SİLMEMELİ

def _save_curated(app, slug, **extra):
    form = {"curated_tone": "karma", "voice_id": "v1", "curated_time": "month",
            "music_mood": "calm", "highlight_color": "#f9a8d4"}
    form.update(extra)
    return app.test_client().post(f"/channels/{slug}/edit", data=form,
                                  follow_redirects=True)


def test_curated_save_preserves_language(app, tmp_path):
    from short_bot.config import load_channel
    _save_curated(app, "jakurate")
    ch = load_channel(tmp_path / "config" / "channels" / "jakurate.yaml")
    assert ch.language == "ja"


def test_curated_save_preserves_font(app, tmp_path):
    """Font kürate formunda yok — kaydetmek onu Montserrat'a düşürmemeli
    (Japoncada Montserrat = kanji tofu)."""
    from short_bot.config import load_channel
    _save_curated(app, "jakurate")
    ch = load_channel(tmp_path / "config" / "channels" / "jakurate.yaml")
    assert ch.reel.font == "Noto Sans JP"


def test_curated_save_keeps_karma_tone(app, tmp_path):
    """Açılırda KARMA var; kaydedici onu mizah'a çevirmemeli (karmadayi'nin YAML'ı
    bugün bu yüzden 'mizah' yazıyor)."""
    from short_bot.config import load_channel
    _save_curated(app, "jakurate", curated_tone="karma")
    ch = load_channel(tmp_path / "config" / "channels" / "jakurate.yaml")
    assert ch.reel.curated_tone == "karma"


def test_curated_save_rejects_unknown_tone(app, tmp_path):
    """Bilinmeyen ton sessizce yazılmasın — geçerli bir kovaya düşsün."""
    from short_bot.config import load_channel
    _save_curated(app, "jakurate", curated_tone="zırva")
    ch = load_channel(tmp_path / "config" / "channels" / "jakurate.yaml")
    assert ch.reel.curated_tone in ("mizah", "duygu", "karma")
