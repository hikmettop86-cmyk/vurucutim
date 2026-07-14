"""Kanal kurma ajanı paneli.

Kullanıcı bir cümle yazar, ajan planı gösterir, kullanıcı "Kur"a basar.
Plan ekranı SES GEREKÇESİNİ göstermeli — yanlış ses kanal KURULMADAN görülsün.
"""
from short_bot.channel_agent import ChannelPlan
from short_bot.db import init_db
from short_bot.dna import DnaFonts, DnaPalette, DnaSpec, DnaTone
from short_bot.voice_picker import VoiceChoice
from short_bot.web import create_app


def _dna():
    return DnaSpec(
        archetype="stat-hero",
        palette=DnaPalette(primary="#0a2540", accent="#2de2e6",
                           bg_gradient=["#0A2540", "#04121F"],
                           body_bg=["#0A2540", "#04121F"]),
        fonts=DnaFonts(), tone=DnaTone(voice="net", style="merak"),
        persona_summary="anlatıcı")


def _app(tmp_path):
    cfg = tmp_path / "config"
    (cfg / "channels").mkdir(parents=True, exist_ok=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\n"
        "log_level: INFO\nclaude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8")
    db = tmp_path / "db.sqlite"
    init_db(db)
    app = create_app(config_dir=cfg, db_path=db, templates_dir=tmp_path / "t",
                     music_root=tmp_path, cache_dir=tmp_path, lock_dir=tmp_path,
                     logs_dir=tmp_path, output_root=tmp_path,
                     secrets_path=tmp_path / "s.yaml", scheduler=False)
    return app, cfg


def _plan(**kw):
    d = dict(language="de", niche="bira bahcesi kulturu",
             evidence="8 outlier; en iyi 175x", name="Bierwissen", slug="bierwissen",
             voice=VoiceChoice(voice_id="elevenlabs_v1", name="Daniel - Teacher",
                               reason="açıklayıcı anlatıcı, bilgi formatına uyar"),
             dna=_dna(), sample_topics=["Bier braucht neun Monate im Keller"])
    d.update(kw)
    return ChannelPlan(**d)


def test_sayfa_acilir(tmp_path):
    a, _ = _app(tmp_path)
    body = a.test_client().get("/channels/agent").data.decode("utf-8")
    assert "Kanal Kurma Ajanı" in body
    assert "Deutsch" in body                  # dil seçici


def test_KISA_nis_reddedilir(tmp_path):
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/agent/plan",
                             data={"niche": "bira", "language": "de"},
                             follow_redirects=True)
    assert "10 karakter" in r.data.decode("utf-8")


def test_PLAN_ekrani_SES_GEREKCESINI_gosterir(tmp_path, monkeypatch):
    """Yanlış ses, kanal KURULMADAN görülmeli."""
    import short_bot.web.routes.channel_agent as CA
    monkeypatch.setattr(CA, "build_plan", lambda *a, **kw: _plan())
    monkeypatch.setattr(CA, "_start_thread", lambda fn: fn())

    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/agent/plan",
                             data={"niche": "bira bahcesi kulturu", "language": "de"},
                             follow_redirects=True)
    body = r.data.decode("utf-8")
    assert "Daniel - Teacher" in body
    assert "açıklayıcı anlatıcı" in body, "ses GEREKÇESİ gösterilmiyor"
    assert "Bierwissen" in body
    assert "8 outlier" in body
    assert "Bier braucht neun Monate" in body


def test_KANIT_YOKSA_panel_KANIT_YOK_der(tmp_path, monkeypatch):
    """Uydurma kanıt yazmayız; kullanıcı neye baktığını bilmeli."""
    import short_bot.web.routes.channel_agent as CA
    monkeypatch.setattr(CA, "build_plan", lambda *a, **kw: _plan(evidence=""))
    monkeypatch.setattr(CA, "_start_thread", lambda fn: fn())
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/agent/plan",
                             data={"niche": "bira bahcesi kulturu", "language": "de"},
                             follow_redirects=True)
    assert "kanıt yok" in r.data.decode("utf-8").lower()


def test_PLAN_PATLARSA_sebebi_gorunur(tmp_path, monkeypatch):
    import short_bot.web.routes.channel_agent as CA

    def _patla(*a, **kw):
        raise RuntimeError("Almanca konusan ses bulunamadi")

    monkeypatch.setattr(CA, "build_plan", _patla)
    monkeypatch.setattr(CA, "_start_thread", lambda fn: fn())
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/agent/plan",
                             data={"niche": "bira bahcesi kulturu", "language": "de"},
                             follow_redirects=True)
    assert "Almanca konusan ses bulunamadi" in r.data.decode("utf-8")


def test_KUR_kanali_olusturur(tmp_path, monkeypatch):
    import short_bot.web.routes.channel_agent as CA
    kuruldu = {}

    monkeypatch.setattr(
        CA, "apply_plan",
        lambda plan, **kw: kuruldu.setdefault("slug", plan.slug) or plan.slug)

    a, _ = _app(tmp_path)
    with CA._LOCK:
        CA._PLANS["job1"] = _plan()

    r = a.test_client().post("/channels/agent/apply/job1", follow_redirects=False)
    assert kuruldu["slug"] == "bierwissen"
    assert r.status_code in (302, 303)
    # /channels/<slug> diye bir rota YOK — oraya yönlendirmek 404 veriyordu.
    assert "/channels/bierwissen/edit-reel" in r.headers["Location"]


def test_BILINMEYEN_is_404(tmp_path):
    a, _ = _app(tmp_path)
    assert a.test_client().post("/channels/agent/apply/yok").status_code == 404


# --- NİŞ BULUCU ------------------------------------------------------------

def test_NIS_BUL_adaylari_KANITLA_listeler(tmp_path, monkeypatch):
    """Kullanıcı 'bana niş bul' derse: adaylar YouTube kanıtıyla ÖLÇÜLMÜŞ gelir."""
    import short_bot.web.routes.channel_agent as CA
    monkeypatch.setattr(CA, "_start_thread", lambda fn: fn())
    monkeypatch.setattr(CA, "find_niches_ai", lambda *a, **kw: [
        {"nis": "Bira kültürü", "neden": "Kanıt: 8 outlier; en iyi 175x",
         "konu_tohumu": "bira bahcesi kulturu ve bira uretiminin gercekleri",
         "kanit_puani": 210.0}])

    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/agent/find",
                             data={"query": "almanya", "language": "de"},
                             follow_redirects=True)
    body = r.data.decode("utf-8")
    assert "Bira kültürü" in body
    assert "175x" in body
    # Aday seçilince plan kurulacak: konu tohumu VE kanıt formda taşınmalı
    assert "bira bahcesi kulturu" in body
    assert 'name="evidence"' in body


def test_ANAHTARSIZ_nis_bulucu_KANITSIZ_der(tmp_path, monkeypatch):
    """YouTube anahtarı yoksa AI moduna düşülür — panel 'kanıtsız' der."""
    import short_bot.web.routes.channel_agent as CA
    monkeypatch.setattr(CA, "_start_thread", lambda fn: fn())
    monkeypatch.setattr(CA, "find_niches_ai", lambda *a, **kw: [
        {"nis": "X", "neden": "y", "konu_tohumu": "z konusu burada uzun"}])
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/agent/find",
                             data={"query": "almanya", "language": "de"},
                             follow_redirects=True)
    assert "kanıtsız" in r.data.decode("utf-8").lower()


def test_NIS_BULUCU_PATLARSA_sebebi_soylenir(tmp_path, monkeypatch):
    import short_bot.web.routes.channel_agent as CA
    monkeypatch.setattr(CA, "_start_thread", lambda fn: fn())

    def _patla(*a, **kw):
        raise RuntimeError("YouTube API anahtari yok")

    monkeypatch.setattr(CA, "find_niches_ai", _patla)
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/agent/find",
                             data={"query": "almanya", "language": "de"},
                             follow_redirects=True)
    assert "YouTube API anahtari yok" in r.data.decode("utf-8")


def test_KISA_sorgu_reddedilir(tmp_path):
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/agent/find",
                             data={"query": "x", "language": "de"},
                             follow_redirects=True)
    assert "Ne hakkında" in r.data.decode("utf-8")


def test_DIL_CELISKISI_panelde_UYARIR(tmp_path, monkeypatch):
    """Metinde 'Almanca' yazıp menüyü Türkçe bırakmak kolay — panel bunu SÖYLEMELİ.
    Otomatik düzeltmiyoruz ('Alman tarihi hakkında TÜRKÇE kanal' da geçerli)."""
    import short_bot.web.routes.channel_agent as CA
    monkeypatch.setattr(CA, "build_plan",
                        lambda *a, **kw: _plan(language="tr", lang_conflict="de"))
    monkeypatch.setattr(CA, "_start_thread", lambda fn: fn())
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/agent/plan",
                             data={"niche": "Almanca bahcecilik kanali istiyorum",
                                   "language": "tr"},
                             follow_redirects=True)
    body = r.data.decode("utf-8")
    assert "Dil çelişkisi" in body
    assert "Deutsch" in body and "Türkçe" in body
    assert "Menü hüküm verir" in body


def test_CELISKI_YOKSA_uyari_YOK(tmp_path, monkeypatch):
    import short_bot.web.routes.channel_agent as CA
    monkeypatch.setattr(CA, "build_plan", lambda *a, **kw: _plan())
    monkeypatch.setattr(CA, "_start_thread", lambda fn: fn())
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/agent/plan",
                             data={"niche": "bira bahcesi kulturu", "language": "de"},
                             follow_redirects=True)
    assert "Dil çelişkisi" not in r.data.decode("utf-8")


def test_plan_ekraninda_BASTAN_baslama_yolu_var(tmp_path, monkeypatch):
    """Plan yanlışsa geri dönebilmelisin — 'Kur' tek çıkış olmamalı."""
    import short_bot.web.routes.channel_agent as CA
    monkeypatch.setattr(CA, "build_plan", lambda *a, **kw: _plan())
    monkeypatch.setattr(CA, "_start_thread", lambda fn: fn())
    a, _ = _app(tmp_path)
    r = a.test_client().post("/channels/agent/plan",
                             data={"niche": "bira bahcesi kulturu", "language": "de"},
                             follow_redirects=True)
    assert "Baştan" in r.data.decode("utf-8")


def test_BEKLERKEN_hangi_ADIMDA_oldugunu_gosterir(tmp_path, monkeypatch):
    """8 dakika 'hazırlanıyor…' yazıp susmak, kullanıcıya takıldı mı söylemez."""
    import short_bot.web.routes.channel_agent as CA
    from short_bot.channel_agent import PLAN_STEPS

    # İşi thread'e ATMA: 'running' durumunda kalsın ki bekleme ekranını görelim.
    monkeypatch.setattr(CA, "_start_thread", lambda fn: None)
    a, _ = _app(tmp_path)
    c = a.test_client()
    r = c.post("/channels/agent/plan",
               data={"niche": "bira bahcesi kulturu", "language": "de"},
               follow_redirects=True)
    body = r.data.decode("utf-8")
    for ad in PLAN_STEPS:
        assert ad in body, f"adım gösterilmiyor: {ad}"
    assert "adım 1/6" in body
    assert "6-8 dk" in body, "süre DÜRÜST verilmiyor (eskiden '2-3 dk' yazıyordu)"


def test_KUR_sonrasi_yonlendirme_404_VERMEZ(tmp_path, monkeypatch):
    """GERÇEK HATA: 'Kur' kanalı kuruyordu ama /channels/<slug>'a yönlendiriyordu —
    öyle bir rota YOK. Kullanıcı 404 görüyordu, kanal ise kurulmuştu.

    Bu testi sahte apply_plan ile yazmak yetmez (redirect'i takip etmeyince 404 kaçar).
    Yönlendirmeyi GERÇEKTEN takip ediyoruz."""
    import short_bot.web.routes.channel_agent as CA
    from short_bot.config import GeneratorConfig, ReelConfig, save_channel
    from short_bot.config import ChannelConfig

    a, cfg = _app(tmp_path)

    def _fake_apply(plan, **kw):
        # Gerçek kurulumun yaptığı TEK şey burada önemli: kanal YAML'ı var olmalı,
        # yoksa edit-reel sayfası kanalı bulamaz.
        save_channel(cfg / "channels" / f"{plan.slug}.yaml", ChannelConfig(
            slug=plan.slug, name=plan.name, keywords=[], rss_locale="hl=de&gl=DE&ceid=DE:de",
            schedule_cron="0 10 * * *", duration_s=40, min_score=7.0,
            max_candidates_per_run=3, template="stat-hero",
            colors={"primary": "#000000", "accent": "#ffffff",
                    "bg_gradient": ["#000000", "#111111"]},
            handle=f"@{plan.slug}", output_dir=f"output/{plan.slug}", enabled=True,
            cta_enabled=False, cta_text="", cta_icons=[], cta_duration_s=0,
            cta_show_handle=False, language=plan.language, dna=plan.dna,
            script_model=None, content_source="generator",
            generator=GeneratorConfig(topic=plan.niche),
            reel=ReelConfig(enabled=True, voice_id=plan.voice.voice_id)))
        return plan.slug

    monkeypatch.setattr(CA, "apply_plan", _fake_apply)
    with CA._LOCK:
        CA._PLANS["job2"] = _plan()

    r = a.test_client().post("/channels/agent/apply/job2", follow_redirects=True)
    assert r.status_code == 200, "kurulumdan sonra 404 — yönlendirme yanlış adrese"
    assert "Bierwissen" in r.data.decode("utf-8")
