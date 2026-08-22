"""Kullanıcının konuyu SEÇTİĞİ üretim: "yeniden üret" + "bu konudan üret".

Kanalı normal çalıştırmak başka bir konu getirir — başlığı LLM seçer. Kusurlu
çıkan bir videoyu aynı konuyla yeniden üretmenin (ya da bankadan istenen başlığı
üretmenin) tek yolu konuyu ZORLAMAK.
"""
import pytest

from short_bot.db import init_db, insert_bank_topics, record_short
from short_bot.generator import build_generator_prompt
from short_bot.web import create_app

_CH_YAML = """slug: balinalar
name: Balina Dünyası
keywords: [balina]
language: tr
schedule_cron: "0 10 * * *"
duration_s: 40
min_score: 7.0
max_candidates_per_run: 3
max_age_hours: 24
template: stat-hero
colors: {primary: '#0a2540', accent: '#2de2e6', bg_gradient: ['#0A2540', '#04121F']}
handle: '@balina'
output_dir: output/balinalar
enabled: false
content_source: generator
generator: {topic: 'balinalar hakkında ilginç bilgiler'}
"""


@pytest.fixture
def app(tmp_path):
    cfg = tmp_path / "config"; (cfg / "channels").mkdir(parents=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models: {dna: opus, default: haiku}\n", encoding="utf-8")
    (cfg / "channels" / "balinalar.yaml").write_text(_CH_YAML, encoding="utf-8")
    db = tmp_path / "db.sqlite"
    eng = init_db(db)
    record_short(eng, channel="balinalar", rss_item_guid=None,
                 title="BALİNALAR NEDEN ŞARKI SÖYLER?", file_path="output/balinalar/a.mp4",
                 duration_s=40, script_json="{}", render_ms=1000)
    insert_bank_topics(eng, "balinalar",
                       [{"topic": "Balina şarkıları 1600 km öteden duyulur",
                         "source_title": "Whale Songs", "views": 2_100_000,
                         "subs": 15_000, "hook_pattern": "merak"}])
    a = create_app(config_dir=cfg, db_path=db, templates_dir=tmp_path / "t",
                   music_root=tmp_path, cache_dir=tmp_path, lock_dir=tmp_path,
                   logs_dir=tmp_path, output_root=tmp_path,
                   secrets_path=tmp_path / "secrets.yaml", scheduler=False)
    return a


@pytest.fixture
def launched(monkeypatch):
    """launch_pipeline'ı yakala — gerçek üretim 10 dk sürer, testte çalıştırmayız."""
    calls = []
    monkeypatch.setattr("short_bot.web.routes.shorts.launch_pipeline",
                        lambda **kw: calls.append(kw))
    monkeypatch.setattr("short_bot.web.runs.launch_pipeline",
                        lambda **kw: calls.append(kw), raising=False)
    return calls


def test_yeniden_uret_ayni_basligi_zorlar(app, launched):
    resp = app.test_client().post("/shorts/1/regenerate")
    assert resp.status_code in (200, 302)
    assert len(launched) == 1
    assert launched[0]["forced_topic"] == "BALİNALAR NEDEN ŞARKI SÖYLER?"
    assert launched[0]["channel"].slug == "balinalar"


def test_yeniden_uret_eskisini_silmez(app, launched):
    from short_bot.web.models import Short
    app.test_client().post("/shorts/1/regenerate")
    with app.app_context():
        assert Short.query.filter_by(id=1).first().deleted_at is None


def test_yeniden_uret_olmayan_short_404(app, launched):
    assert app.test_client().post("/shorts/999/regenerate").status_code == 404
    assert not launched


def test_bankadan_uret_konuyu_zorlar(app, monkeypatch):
    calls = []
    monkeypatch.setattr("short_bot.web.runs.launch_pipeline",
                        lambda **kw: calls.append(kw))
    import short_bot.web.routes.topic_bank as tb
    monkeypatch.setattr(tb, "launch_pipeline", lambda **kw: calls.append(kw),
                        raising=False)
    resp = app.test_client().post("/channels/balinalar/topic-bank/1/produce")
    assert resp.status_code in (200, 302)
    assert len(calls) == 1
    assert calls[0]["forced_topic"] == "Balina şarkıları 1600 km öteden duyulur"


def test_bankada_olmayan_konu_404(app, monkeypatch):
    calls = []
    monkeypatch.setattr("short_bot.web.runs.launch_pipeline",
                        lambda **kw: calls.append(kw))
    assert app.test_client().post(
        "/channels/balinalar/topic-bank/999/produce").status_code == 404
    assert not calls


def test_topic_bank_sayfasinda_uret_dugmesi_var(app):
    body = app.test_client().get("/channels/balinalar/topic-bank").data.decode("utf-8")
    assert "/topic-bank/1/produce" in body


def test_detay_sayfasinda_yeniden_uret_dugmesi_var(app):
    body = app.test_client().get("/shorts/1").data.decode("utf-8")
    assert "/shorts/1/regenerate" in body


# ——— prompt tarafı ———

def _cfg():
    import pathlib
    import tempfile

    from short_bot.config import load_channel
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "balinalar.yaml").write_text(_CH_YAML, encoding="utf-8")
    return load_channel(d / "balinalar.yaml")


def _dna():
    from short_bot.dna import DnaFonts, DnaPalette, DnaSpec, DnaTone
    return DnaSpec(
        archetype="stat-hero",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(headline="Anton", body="Inter"),
        tone=DnaTone(voice="meraklı", style="kısa", forbidden=["klişe"],
                     sentence_max_words=14, body_max_chars=300,
                     headline_style_hint="iki satır"),
        category_icon="🐋", persona_summary="Balina kanalı.")


def _prompt(**kw):
    return build_generator_prompt(channel=_cfg(), dna=_dna(),
                                  forbidden_texts=["Eski başlık"],
                                  topic_distribution={"balina": 3}, **kw)


PROVEN = [{"id": 7, "topic": "Banka konusu", "views": 1000, "subs": 100}]


def test_zorlanan_konu_prompta_girer():
    p = _prompt(forced_topic="BALİNALAR NEDEN ŞARKI SÖYLER?")
    assert "BALİNALAR NEDEN ŞARKI SÖYLER?" in p
    assert "KONU ZORUNLU" in p


def test_zorlanan_konu_banka_ve_yasak_bloklarini_susturur():
    # Bunlar kalırsa LLM zorlanan konudan BAŞKA bir konuya kayar: banka seçimi
    # "ZORUNLU" diyor, yasak listesi de aynı başlığı üretmeyi engelliyor.
    p = _prompt(forced_topic="BALİNALAR NEDEN ŞARKI SÖYLER?", proven_topics=PROVEN)
    assert "Banka konusu" not in p
    assert "Eski başlık" not in p


def test_zorlanmayan_konuda_banka_blogu_durur():
    p = _prompt(proven_topics=PROVEN)
    assert "Banka konusu" in p and "Eski başlık" in p


def test_uretilen_konu_listeden_duser_ve_DB_DE_KALIR(app, monkeypatch):
    """Üretime verilen konu ANINDA 'used' — mükerrer üretimi engelleyen şey bu.

    Eskiden banka kaydı hiç işaretlenmiyordu: kullanıcı aynı satıra tekrar basıp
    aynı videoyu ikinci kez üretebiliyordu (üretim prompt'u da onu hâlâ aktif
    görüyordu).
    """
    from short_bot.db import all_bank_topics, init_db
    monkeypatch.setattr("short_bot.web.runs.launch_pipeline", lambda **kw: None)
    c = app.test_client()
    c.post("/channels/balinalar/topic-bank/1/produce")

    eng = init_db(app.config["SHORTBOT_DB_PATH"])
    rows = all_bank_topics(eng, "balinalar")
    assert len(rows) == 1, "kayıt DB'den SİLİNMEMELİ"
    assert rows[0]["status"] == "used"

    # Konu adı flash mesajında geçebilir; ölçüt SATIRIN kendisi (üret düğmesi).
    body = c.get("/channels/balinalar/topic-bank").data.decode("utf-8")
    assert "/topic-bank/1/produce" not in body, "üretilen konu listede kalmış"


def test_ayni_konu_ikinci_kez_uretilemez(app, monkeypatch):
    calls = []
    monkeypatch.setattr("short_bot.web.runs.launch_pipeline",
                        lambda **kw: calls.append(kw))
    c = app.test_client()
    assert c.post("/channels/balinalar/topic-bank/1/produce").status_code in (200, 302)
    assert c.post("/channels/balinalar/topic-bank/1/produce").status_code == 404
    assert len(calls) == 1, "aynı konu ikinci kez üretime verildi"
