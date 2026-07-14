from short_bot.db import init_db, insert_bank_topics, all_bank_topics
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


def _client(tmp_path):
    cfg = tmp_path / "config"; (cfg / "channels").mkdir(parents=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models: {dna: opus, default: haiku}\nai_backend: openrouter\n",
        encoding="utf-8")
    (cfg / "channels" / "balinalar.yaml").write_text(_CH_YAML, encoding="utf-8")
    app = create_app(config_dir=cfg, db_path=tmp_path / "db.sqlite",
                     templates_dir=tmp_path / "t", music_root=tmp_path,
                     cache_dir=tmp_path, lock_dir=tmp_path, logs_dir=tmp_path,
                     output_root=tmp_path, secrets_path=tmp_path / "secrets.yaml",
                     scheduler=False)
    return app, tmp_path / "db.sqlite"


def test_topic_bank_page_lists_rows(tmp_path):
    app, db = _client(tmp_path)
    eng = init_db(db)
    insert_bank_topics(eng, "balinalar",
                       [{"topic": "Balina şarkıları", "source_title": "Whale Songs",
                         "views": 2100000, "subs": 15000, "hook_pattern": "merak"}])
    body = app.test_client().get("/channels/balinalar/topic-bank").data.decode("utf-8")
    assert "Balina şarkıları" in body and "Konu Bankası" in body
    assert "topic-bank/refresh" in body                    # yenile düğmesi


def test_topic_bank_refresh_runs_in_thread(tmp_path, monkeypatch):
    app, _ = _client(tmp_path)
    # rota YouTube API anahtarı ister (NexLev kaldırıldı) → secrets'a anahtar yaz
    (tmp_path / "secrets.yaml").write_text("youtube_api_key: AIzaTEST\n",
                                           encoding="utf-8")
    calls = {}
    import short_bot.web.routes.topic_bank as tb

    def fake_refresh(eng, slug, query, **kw):
        calls["slug"] = slug; calls["query"] = query
        calls["api_keys"] = kw.get("api_keys")
        return {"added": 2, "skipped_dup": 0, "rejected": 0}
    monkeypatch.setattr(tb, "refresh_topic_bank", fake_refresh)
    # thread'i senkron çalıştır (test determinizmi)
    monkeypatch.setattr(tb, "_start_thread", lambda fn: fn())
    r = app.test_client().post("/channels/balinalar/topic-bank/refresh",
                               follow_redirects=False)
    assert r.status_code in (302, 303)
    assert calls["slug"] == "balinalar" and "balina" in calls["query"]
    assert calls["api_keys"] == ["AIzaTEST"]


def test_API_ANAHTARI_YOKKEN_yenileme_YINE_KOSAR(tmp_path, monkeypatch):
    """DAVRANIŞ DEĞİŞTİ (ölçümle).

    Eskiden anahtar yoksa iş HİÇ başlatılmıyordu ve banka hiç dolmuyordu. Ama konu
    üretimi artık YouTube'a bağlı değil: anahtar yalnız KANIT toplamak için. Yoksa
    model kendi bilgisiyle üretir — banka asla kurumaz.
    """
    app, _ = _client(tmp_path)
    import short_bot.web.routes.topic_bank as tb
    calls = {}

    def fake_refresh(eng, slug, query, **kw):
        calls["api_keys"] = kw.get("api_keys")
        return {"added": 3, "skipped_dup": 0, "rejected": 0}

    monkeypatch.setattr(tb, "refresh_topic_bank", fake_refresh)
    monkeypatch.setattr(tb, "_start_thread", lambda fn: fn())
    r = app.test_client().post("/channels/balinalar/topic-bank/refresh",
                               follow_redirects=True)
    assert calls["api_keys"] == [], "anahtarsız da madenciye gidilmeli"
    body = r.data.decode("utf-8")
    assert "KANIT OLMADAN" in body, "kullanıcıya kanıtsız üretildiği söylenmeli"


def test_channels_page_links_topic_bank(tmp_path):
    """Kanal kartında 🎯 Konu Bankası linki görünür (generator kanalı)."""
    app, _ = _client(tmp_path)
    body = app.test_client().get("/channels").data.decode("utf-8")
    assert "/channels/balinalar/topic-bank" in body


def test_topic_bank_save_reference_channels_roundtrip(tmp_path):
    """Referans kanallar formu YAML'a yazılır ve sayfada geri görünür."""
    import yaml as _yaml
    app, _ = _client(tmp_path)
    c = app.test_client()
    r = c.post("/channels/balinalar/topic-bank/refs", data={
        "reference_channels": "https://www.youtube.com/@BilimleBak/shorts\n@Digeri\n\n@Digeri",
    }, follow_redirects=False)
    assert r.status_code in (302, 303)
    data = _yaml.safe_load((tmp_path / "config" / "channels" / "balinalar.yaml")
                           .read_text(encoding="utf-8"))
    assert data["reference_channels"] == [
        "https://www.youtube.com/@BilimleBak/shorts", "@Digeri"]   # dup elendi
    body = c.get("/channels/balinalar/topic-bank").data.decode("utf-8")
    assert "@BilimleBak" in body and "Referans kanallar" in body


def test_topic_bank_refresh_passes_reference_channels(tmp_path, monkeypatch):
    app, _ = _client(tmp_path)
    (tmp_path / "secrets.yaml").write_text("youtube_api_key: AIzaTEST\n",
                                           encoding="utf-8")
    ch_yaml = tmp_path / "config" / "channels" / "balinalar.yaml"
    ch_yaml.write_text(ch_yaml.read_text(encoding="utf-8")
                       + "reference_channels: ['@BilimleBak']\n", encoding="utf-8")
    calls = {}
    import short_bot.web.routes.topic_bank as tb

    def fake_refresh(eng, slug, query, **kw):
        calls["refs"] = kw.get("reference_channels")
        return {"added": 1, "skipped_dup": 0, "rejected": 0}
    monkeypatch.setattr(tb, "refresh_topic_bank", fake_refresh)
    monkeypatch.setattr(tb, "_start_thread", lambda fn: fn())
    app.test_client().post("/channels/balinalar/topic-bank/refresh")
    assert calls["refs"] == ["@BilimleBak"]


def test_topic_bank_reject(tmp_path):
    app, db = _client(tmp_path)
    eng = init_db(db)
    insert_bank_topics(eng, "balinalar",
                       [{"topic": "kötü konu", "source_title": "", "views": 0,
                         "subs": 0, "hook_pattern": ""}])
    rid = all_bank_topics(eng, "balinalar")[0]["id"]
    app.test_client().post(f"/channels/balinalar/topic-bank/{rid}/reject")
    assert all_bank_topics(eng, "balinalar")[0]["status"] == "rejected"


# --- KAYNAK ROZETİ + DENETLE DÜĞMESİ ---------------------------------------
# Kanıtsız bir konuyu kanıtlı sanmak sessiz bir yanılgıdır. Ve bankadaki ESKİ çöp
# (ölçüldü: vucudun'da %85) temizlenebilmeli.

def test_KAYNAK_rozeti_gorunur(tmp_path):
    app, db = _client(tmp_path)
    insert_bank_topics(init_db(db), "balinalar", [
        {"topic": "Kanitli konu", "source_title": "V", "views": 100_000,
         "subs": 1_000, "source": "search"},
        {"topic": "Modelin urettigi konu", "source_title": "", "views": 0,
         "subs": 0, "source": "llm"},
        {"topic": "Referanstan gelen", "source_title": "R", "views": 50_000,
         "subs": 2_000, "source": "reference"}])
    body = app.test_client().get("/channels/balinalar/topic-bank").data.decode("utf-8")
    assert "model önerisi" in body
    assert "referans kanal" in body
    assert "100× patlama" in body


def test_KANITSIZ_konuda_SIFIR_IZLENME_yazmaz(tmp_path):
    """'0 izlenme / 0 abone' yazmak yanıltıcı — kanıt YOK, sıfır DEĞİL."""
    app, db = _client(tmp_path)
    insert_bank_topics(init_db(db), "balinalar", [
        {"topic": "Modelin urettigi konu", "source_title": "", "views": 0,
         "subs": 0, "source": "llm"}])
    body = app.test_client().get("/channels/balinalar/topic-bank").data.decode("utf-8")
    assert "0</span> izlenme" not in body


def test_DENETLE_dugmesi_var(tmp_path):
    app, db = _client(tmp_path)
    insert_bank_topics(init_db(db), "balinalar", [
        {"topic": "Bir konu", "source_title": "V", "views": 1, "subs": 1}])
    body = app.test_client().get("/channels/balinalar/topic-bank").data.decode("utf-8")
    assert "/topic-bank/audit" in body
    assert "Bankayı denetle" in body


def test_BOS_bankada_denetle_dugmesi_YOK(tmp_path):
    app, _ = _client(tmp_path)
    body = app.test_client().get("/channels/balinalar/topic-bank").data.decode("utf-8")
    assert "Bankayı denetle" not in body


def _sahte_sonnet():
    """Prompt'u GERÇEKTEN okuyan sahte model.

    all_bank_topics en yeniyi ÖNCE döndürüyor; sabit indekse yargı bağlamak YANLIŞ
    konuyu reddettirir ve testi sessizce yalancı yapar (ilk yazışımda tam bu oldu).
    """
    def _f(prompt, schema, **kw):
        yargilar = []
        for satir in prompt.splitlines():
            bas, _, metin = satir.strip().partition(".")
            if bas.isdigit():
                cop = "ici bos" in metin.lower()
                yargilar.append({"index": int(bas), "solid": not cop,
                                 "reason": "içi boş" if cop else ""})
        return schema.model_validate({"verdicts": yargilar})
    return _f


def test_denetle_rotasi_COP_konuyu_REDDEDER(tmp_path, monkeypatch):
    """Rota SENKRON: gerçek audit_bank koşar, yalnız LLM sahte. Kullanıcı sonucu
    ANINDA görmeli — "birkaç dakika içinde biter" diyen panel sonucu asla göstermez."""
    import short_bot.web.routes.topic_bank as tb
    app, db = _client(tmp_path)
    eng = init_db(db)
    insert_bank_topics(eng, "balinalar", [
        {"topic": "Ici bos genelleme", "source_title": "V1", "views": 1, "subs": 1},
        {"topic": "Saglam somut olgu", "source_title": "V2", "views": 1, "subs": 1}])

    monkeypatch.setattr(tb, "_sonnet", _sahte_sonnet)
    r = app.test_client().post("/channels/balinalar/topic-bank/audit",
                               follow_redirects=True)
    body = r.data.decode("utf-8")
    assert "2 konu denetlendi" in body
    assert "1 tanesi reddedildi" in body

    durum = {x["topic"]: x["status"] for x in all_bank_topics(eng, "balinalar")}
    assert durum["Ici bos genelleme"] == "rejected"
    assert durum["Saglam somut olgu"] == "active"


def test_denetim_PATLARSA_sebebi_soylenir(tmp_path, monkeypatch):
    import short_bot.web.routes.topic_bank as tb
    app, db = _client(tmp_path)
    insert_bank_topics(init_db(db), "balinalar", [
        {"topic": "Konu", "source_title": "V", "views": 1, "subs": 1}])

    def _patla():
        raise RuntimeError("sonnet kurulu degil")

    monkeypatch.setattr(tb, "_sonnet", _patla)
    r = app.test_client().post("/channels/balinalar/topic-bank/audit",
                               follow_redirects=True)
    assert "Denetim başarısız" in r.data.decode("utf-8")
