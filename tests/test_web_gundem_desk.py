"""Canlı Gündem masası (Masa yönü): kuyruk + seçili haberin dosyası + tek tıkla üretim."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from short_bot.models import NewsItem
from short_bot.web import create_app

_SETTINGS = ("ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
             "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
             "claude_models: {dna: opus, default: haiku}\n")


def _ch(slug, voice=False, region="TR"):
    v = ("voice:\n  enabled: true\n  provider: cartesia\n  voice_id: v\n  speed: 1.05\n" if voice else "")
    return f"""\
slug: {slug}
name: {slug.title()}
keywords: []
language: tr
content_source: trends
trends_region: {region}
schedule_cron: 0 7-22/3 * * *
duration_s: 6
min_score: 6.0
max_candidates_per_run: 25
template: flas
colors:
  primary: '#d0021b'
  accent: '#ffe600'
  bg_gradient: ['#3a3a3a', '#141414']
handle: '@{slug}'
output_dir: output/{slug}
enabled: true
{v}"""


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(_SETTINGS, encoding="utf-8")
    (cfg_dir / "channels" / "gundem.yaml").write_text(_ch("gundem"), encoding="utf-8")
    (cfg_dir / "channels" / "gundem-yorum.yaml").write_text(_ch("gundem-yorum", voice=True), encoding="utf-8")
    (cfg_dir / "channels" / "berlin.yaml").write_text(_ch("berlin", region="DE"), encoding="utf-8")
    (tmp_path / "data").mkdir()
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                      secrets_path=tmp_path / "data" / "secrets.yaml", scheduler=False)


ITEMS = [
    NewsItem(guid="https://a/1", title="Marmara 8 saatte 36 kez sallandı", link="https://a/1",
             source="Milliyet", pub_date=datetime.now(timezone.utc) - timedelta(hours=16),
             thumb_url="https://img/1.jpg",
             description="Google Trends · 100.000 arama · +%1.000 · istanbul deprem",
             trend_volume=100000, extra_links=("https://b/2", "https://c/3"),
             trend_growth_pct=1000, trend_related=("istanbul deprem", "adalar fayı", "kandilli"),
             trend_articles=(("NTV", "Adalar çevresindeki depremler"), ("Onedio", "Gece boyu 51 deprem"))),
    NewsItem(guid="https://c/3", title="Asgari ücrete ara zam", link="https://c/3", source="Dünya",
             pub_date=None, thumb_url=None, description="Google Trends · 10.000 arama",
             trend_volume=10000, trend_growth_pct=0, trend_related=("asgari ücret zam",)),
]


@pytest.fixture
def fake_trends(monkeypatch):
    seen = {}

    def _fetch(region, **kw):
        seen["region"] = region
        seen["kw"] = kw
        return ITEMS if region == "TR" else []
    monkeypatch.setattr("short_bot.web.routes.gundem.fetch_trending_items", _fetch)
    return seen


# --- kuyruk -------------------------------------------------------------------------

def test_desk_lists_queue_with_volume_growth_and_age(app, fake_trends):
    body = app.test_client().get("/gundem?region=TR").data.decode("utf-8")
    assert "Marmara 8 saatte 36 kez sallandı" in body and "100 B+" in body
    assert "%1.000" in body and "16 sa" in body and "3 kaynak" in body
    assert "Asgari ücrete ara zam" in body and "10 B+" in body
    # NOT: .html.j2 uzantısında Flask autoescape KAPALI (projenin bilinen tuzağı) —
    # bu yüzden şablon dış veriyi |e ile elle kaçırır, & de elle &amp; yazılır.
    assert 'href="/gundem?region=TR&amp;guid=https%3A//a/1"' in body
    assert 'hx-trigger="every 300s"' in body
    assert fake_trends["kw"]["max_age_minutes"] == 30


def test_list_partial_force_refresh(app, fake_trends):
    r = app.test_client().get("/gundem/list?region=TR&force=1")
    assert r.status_code == 200 and fake_trends["kw"]["max_age_minutes"] == 0
    assert "Marmara" in r.data.decode("utf-8")


# --- detay paneli --------------------------------------------------------------------

def test_detail_shows_sources_related_and_channels(app, fake_trends):
    body = app.test_client().get("/gundem?region=TR").data.decode("utf-8")
    # ilk (üretilmemiş) haber kendiliğinden seçili
    assert "KAYNAKLAR" in body and "Milliyet" in body and "NTV" in body and "Onedio" in body
    assert "Adalar çevresindeki depremler" in body and "Gece boyu 51 deprem" in body
    assert "İNSANLAR NE ARIYOR" in body and "adalar fayı" in body
    assert "100.000" in body and "KART BÖYLE ÇIKACAK" in body
    assert "KANAL DURUMU" in body and "Gundem-Yorum" in body
    # üretim düğmeleri: iki TR kanalı, DE kanalı YOK
    assert 'value="gundem-yorum"' in body and 'value="gundem"' in body
    assert 'value="berlin"' not in body
    assert "3 kaynaktan tarafsız yorum" in body


def test_selecting_by_guid_switches_detail(app, fake_trends):
    body = app.test_client().get("/gundem?region=TR&guid=https://c/3").data.decode("utf-8")
    assert "asgari ücret zam" in body
    assert "10.000" in body


def test_produced_item_is_marked_and_offers_a_followup(app, fake_trends, tmp_path):
    """Üretilmiş haber KİLİTLİ değil: gelişme olduğunda takip videosu üretilir.
    (Ölçüm 2026-08-20: arama talebi tekrar ediyor, tek video onu karşılamıyor.)"""
    from short_bot.db import init_db, mark_processed
    eng = init_db(tmp_path / "x.sqlite")
    mark_processed(eng, guid="https://a/1", channel="gundem", title="t")
    body = app.test_client().get("/gundem?region=TR").data.decode("utf-8")
    assert "✓ üretildi" in body                       # kuyrukta işaret
    # seçim üretilmemiş ilk habere kayar
    assert "asgari ücret zam" in body
    # üretilmiş haberi elle seçince: düğme açık ve takip modunda
    done = app.test_client().get("/gundem?region=TR&guid=https://a/1").data.decode("utf-8")
    assert "↻ Takip" in done and 'name="followup" value="1"' in done
    assert "disabled" not in done.split("data-produce")[1][:900]


def test_queue_marks_question_intent(app, monkeypatch):
    """Soru niyetli trend kuyrukta işaretlenir — cevap veren format onun işidir.
    Saf olay ("istanbul deprem") işaretlenmez."""
    items = [
        NewsItem(guid="https://q/1", title="Asgari ücret", link="l", source="Dünya",
                 pub_date=None, thumb_url=None, description="d", trend_volume=20000,
                 trend_related=("asgari ücrete zam gelecek mi", "asgari ücret")),
        NewsItem(guid="https://e/2", title="Deprem", link="l", source="NTV",
                 pub_date=None, thumb_url=None, description="d", trend_volume=90000,
                 trend_related=("istanbul deprem", "son dakika deprem")),
    ]
    monkeypatch.setattr("short_bot.web.routes.gundem.fetch_trending_items",
                        lambda region, **kw: items if region == "TR" else [])
    body = app.test_client().get("/gundem?region=TR").data.decode("utf-8")
    assert body.count(">soru<") == 1


def test_followup_carries_previous_narration_into_the_item(app, fake_trends, monkeypatch, tmp_path):
    """Takip üretimi önceki metni prompta taşır; taşımazsa video aynı şeyi tekrar anlatır."""
    import json
    from short_bot.db import init_db, record_short
    eng = init_db(tmp_path / "x.sqlite")
    record_short(eng, channel="gundem", rss_item_guid="https://a/1", title="ÖNCEKİ KART",
                 file_path="f.mp4", duration_s=6,
                 script_json=json.dumps({"narration_text": "Gece 36 sarsıntı oldu."}),
                 render_ms=1)
    seen = {}
    monkeypatch.setattr("short_bot.web.routes.gundem.launch_pipeline",
                        lambda **kw: seen.update(kw))
    app.test_client().post("/gundem/produce", data={
        "region": "TR", "channel_slug": "gundem-yorum", "guid": "https://a/1",
        "followup": "1"})
    it = seen["preselected_item"]
    assert "ÖNCEKİ KART" in it.followup_of and "36 sarsıntı" in it.followup_of
    assert it.trend_volume == 100000          # haberin geri kalanı bozulmadı


def test_followup_without_previous_video_falls_back_to_normal(app, fake_trends, monkeypatch):
    seen = {}
    monkeypatch.setattr("short_bot.web.routes.gundem.launch_pipeline",
                        lambda **kw: seen.update(kw))
    r = app.test_client().post("/gundem/produce", data={
        "region": "TR", "channel_slug": "gundem", "guid": "https://a/1",
        "followup": "1"}, follow_redirects=True)
    assert seen["preselected_item"].followup_of == ""
    assert "Önceki video bulunamadı" in r.data.decode("utf-8")


def test_normal_produce_never_sets_followup(app, fake_trends, monkeypatch):
    """Otomatik/normal üretim ASLA takip moduna girmez — yoksa aynı haberi
    iki kez anlatan bot oluruz."""
    seen = {}
    monkeypatch.setattr("short_bot.web.routes.gundem.launch_pipeline",
                        lambda **kw: seen.update(kw))
    app.test_client().post("/gundem/produce", data={
        "region": "TR", "channel_slug": "gundem", "guid": "https://a/1"})
    assert seen["preselected_item"].followup_of == ""


def test_known_gate_score_is_shown(app, fake_trends, tmp_path):
    from short_bot.db import init_db, record_rss_item
    eng = init_db(tmp_path / "x.sqlite")
    record_rss_item(eng, guid="https://a/1", channel="gundem", title="t", link="l", source="s",
                    pub_date=None, thumb_url=None, score=3.0, status="below_threshold")
    body = app.test_client().get("/gundem?region=TR&guid=https://a/1").data.decode("utf-8")
    assert "Kapı" in body and "3/10" in body and "eşiğin altında" in body


def test_empty_region_shows_hint(app, fake_trends):
    body = app.test_client().get("/gundem?region=DE").data.decode("utf-8")
    assert "trend bulunamadı" in body


# --- üretim --------------------------------------------------------------------------

def test_produce_launches_pipeline_with_full_cached_item(app, fake_trends, monkeypatch):
    seen = {}
    monkeypatch.setattr("short_bot.web.routes.gundem.launch_pipeline", lambda **kw: seen.update(kw))
    r = app.test_client().post("/gundem/produce", data={"region": "TR", "channel_slug": "gundem-yorum",
                                                        "guid": "https://a/1"})
    assert r.status_code == 302 and "guid=" in r.headers["Location"]
    assert seen["channel"].slug == "gundem-yorum" and seen["trigger"] == "manual_gundem"
    it = seen["preselected_item"]
    assert it.guid == "https://a/1" and it.trend_volume == 100000
    assert it.extra_links == ("https://b/2", "https://c/3")
    assert it.trend_articles[0] == ("NTV", "Adalar çevresindeki depremler")


def test_produce_unknown_guid_flashes(app, fake_trends, monkeypatch):
    monkeypatch.setattr("short_bot.web.routes.gundem.launch_pipeline",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("çağrılmamalı")))
    r = app.test_client().post("/gundem/produce", data={"channel_slug": "gundem", "guid": "https://yok"},
                               follow_redirects=True)
    assert r.status_code == 200 and "artık listede değil" in r.data.decode("utf-8")


def test_nav_has_gundem_link(app, fake_trends):
    body = app.test_client().get("/gundem").data.decode("utf-8")
    assert 'href="/gundem"' in body


def test_external_text_is_escaped(app, fake_trends, monkeypatch):
    """.html.j2'de autoescape kapalı: Trends'ten gelen başlık HTML olarak girmemeli."""
    from short_bot.models import NewsItem
    evil = NewsItem(guid="https://x/1", title='<img src=x onerror="alert(1)">', link="https://x/1",
                    source="<b>Kaynak</b>", pub_date=None, thumb_url=None, description="d",
                    trend_volume=5000, trend_related=("<script>alert(2)</script>",),
                    trend_articles=(("<i>NTV</i>", "<u>Başlık</u>"),))
    monkeypatch.setattr("short_bot.web.routes.gundem.fetch_trending_items", lambda region, **kw: [evil])
    body = app.test_client().get("/gundem?region=TR").data.decode("utf-8")
    # ham etiket YOK, kaçırılmış metin VAR
    assert "<img src=x" not in body and "<script>alert(2)" not in body
    assert "<b>Kaynak</b>" not in body
    assert "&lt;img src=x" in body and "&lt;b&gt;Kaynak" in body
    assert "&lt;u&gt;Başlık" in body and "&lt;script&gt;alert(2)" in body


def test_card_mock_follows_the_regions_channel_identity(tmp_path, monkeypatch):
    """Masadaki 'kart böyle çıkacak' maketi SABİT Türk kimliğindeydi (kırmızı+sarı,
    'MANŞET', 'SIRADA'): Almanca kanalın masasında yanlış bir kart gösteriyordu.

    Kendi uygulamasını kurar — kanal dosyası create_app'ten ÖNCE yazılmalı."""
    import yaml
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(_SETTINGS, encoding="utf-8")
    (cfg_dir / "channels" / "gundem.yaml").write_text(_ch("gundem"), encoding="utf-8")
    de = yaml.safe_load(_ch("de-kanal"))
    de.update({"language": "de", "trends_region": "DE", "template": "eilmeldung",
               "colors": {"primary": "#0b3b73", "accent": "#e2001a",
                          "bg_gradient": ["#1d2632", "#10141a"]}})
    (cfg_dir / "channels" / "de-kanal.yaml").write_text(
        yaml.safe_dump(de, allow_unicode=True), encoding="utf-8")
    (tmp_path / "data").mkdir()
    app = create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite",
                     secrets_path=tmp_path / "data" / "secrets.yaml", scheduler=False)
    monkeypatch.setattr("short_bot.web.routes.gundem.fetch_trending_items",
                        lambda region, **kw: (ITEMS if region == "TR" else [ITEMS[0]]))
    de_body = app.test_client().get("/gundem?region=DE").data.decode("utf-8")
    assert "SCHLAGZEILE" in de_body and "BAUCHBINDE" in de_body and "WEITER" in de_body
    assert "#0b3b73" in de_body and "Eilmeldung kimliği" in de_body
    tr_body = app.test_client().get("/gundem?region=TR").data.decode("utf-8")
    assert "MANŞET" in tr_body and "SIRADA" in tr_body and "Flaş kimliği" in tr_body
