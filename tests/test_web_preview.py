import pytest

from short_bot.web import create_app


@pytest.fixture
def app(tmp_path):
    cfg_dir = tmp_path / "config"
    (cfg_dir / "channels").mkdir(parents=True)
    (cfg_dir / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\n"
        "fuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models:\n  dna: opus\n  default: haiku\n",
        encoding="utf-8",
    )
    (cfg_dir / "channels" / "demo-tr.yaml").write_text(
        "slug: demo-tr\nname: Demo\nlanguage: tr\nkeywords: [a]\n"
        "schedule_cron: ''\nduration_s: 6\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\ntemplate: newscast\n"
        "colors: {primary: '#c81e1e', accent: '#ffea3b', bg_gradient: ['#1a3b6b','#0a1a3b']}\n"
        "handle: '@demo'\noutput_dir: output/demo\nenabled: true\n"
        "cta: {enabled: false, text: '', icons: [], duration_s: 0, show_handle: false}\n",
        encoding="utf-8",
    )
    return create_app(config_dir=cfg_dir, db_path=tmp_path / "x.sqlite", scheduler=False)


def test_preview_returns_html(app):
    """VARSAYILAN ARTIK EN KÖTÜ HÂL. Eskiden `sample_script_tr.json` ("ARA ZAM",
    7/9/138 karakter) gösteriliyordu; üretimin maksimumu 25/35/302 olduğu için
    önizleme taşmayı ASLA gösteremiyordu. Kısa örnek `?stres=ornek` ile duruyor.
    """
    client = app.test_client()
    resp = client.get("/preview/demo-tr")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    assert "ARA ZAM" in client.get("/preview/demo-tr?stres=ornek").data.decode("utf-8")


def test_preview_cta_parametresi_artik_etkisiz(app):
    """Beğeni/abone öğeleri KALDIRILDI (2026-07-16): eski ?cta_enabled=1
    parametresi sessizce yok sayılır, ekranda BEĞEN/ABONE çıkmaz."""
    client = app.test_client()
    resp = client.get("/preview/demo-tr?cta_enabled=1")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "ABONE OL" not in body and "BEĞEN" not in body


def test_preview_404_for_missing_channel(app):
    client = app.test_client()
    resp = client.get("/preview/nonexistent")
    assert resp.status_code == 404


def test_preview_overrides_primary_color(app):
    client = app.test_client()
    resp = client.get("/preview/demo-tr?primary=%23ff00ff")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "#ff00ff" in body


# --- ÖNİZLEME EN KÖTÜ HÂLİ GÖSTERMELİ -------------------------------------
#
# KULLANICI SORUSU (2026-08-21): "bu önizleme ekranı ne kadar doğru
# gösteriyor" → ÖLÇÜLDÜ: örnek senaryo `header_top=7`, `header_bottom=9`,
# `body=138` karakter; üretimin gerçek maksimumu 25/35/302 (1159 senaryo).
# Yani önizleme EN İYİ HÂLİ gösteriyordu ve taşmayı ASLA gösteremezdi —
# kullanıcı panelde temiz kart görüp yayında kesik metin alıyordu.
#
# Kullanıcı kararı: "o zaman yenisine göre yap" → arketip kapısının uç
# metinleri (`UC_METINLER`) burada da kullanılır.

def _kare(c, slug, **q):
    from urllib.parse import urlencode
    return c.get(f"/preview/{slug}?" + urlencode(q)).get_data(as_text=True)


def test_VARSAYILAN_en_uzun_stres_metni(app):
    from short_bot.archetype_gate import UC_METINLER
    en_uzun = max(UC_METINLER, key=lambda s: len(s.body_paragraph))
    html = _kare(app.test_client(), "demo-tr")
    assert en_uzun.header_top in html
    assert en_uzun.body_paragraph[:40] in html


def test_ORNEK_senaryo_hala_istenebilir(app):
    """Kısa/gerçekçi metin de bir bilgi — ama artık VARSAYILAN değil."""
    html = _kare(app.test_client(), "demo-tr", stres="ornek")
    from short_bot.archetype_gate import UC_METINLER
    en_uzun = max(UC_METINLER, key=lambda s: len(s.body_paragraph))
    assert en_uzun.body_paragraph[:40] not in html


def test_HER_STRES_DURUMU_secilebilir(app):
    from short_bot.archetype_gate import UC_METINLER
    c = app.test_client()
    for i, s in enumerate(UC_METINLER):
        html = _kare(c, "demo-tr", stres=str(i))
        assert s.header_top in html, i


def test_GECERSIZ_stres_indeksi_KIRMAZ(app):
    c = app.test_client()
    for kotu in ("99", "-1", "abc", ""):
        assert app.test_client().get(f"/preview/demo-tr?stres={kotu}").status_code == 200


def test_onizleme_ANIMASYON_stilini_de_gecirir(app):
    """Üretim `render_frames`e `animation_style` veriyor; önizleme vermiyordu
    → hareketli öğeler farklı yerde duruyordu."""
    import inspect

    from short_bot.web.routes import preview as P
    kaynak = inspect.getsource(P.preview)
    assert "animation_style" in kaynak


def test_duzenleme_sayfasinda_STRES_SECICI_var(tmp_path):
    """Kullanıcı hangi metni gördüğünü BİLMELİ: en kötü hâl mi, kısa örnek mi."""
    from short_bot.web import create_app
    cfg = tmp_path / "config"
    (cfg / "channels").mkdir(parents=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\n"
        "log_level: INFO\nclaude_models: {dna: opus, default: haiku}\n",
        encoding="utf-8")
    (cfg / "channels" / "demo-tr.yaml").write_text(
        "slug: demo-tr\nname: Demo\nlanguage: tr\nkeywords: [a]\n"
        "schedule_cron: '0 9 * * *'\nduration_s: 6\nmin_score: 6.0\n"
        "max_candidates_per_run: 10\ntemplate: newscast\n"
        "colors: {primary: '#c81e1e', accent: '#ffea3b', "
        "bg_gradient: ['#1a3b6b','#0a1a3b']}\n"
        "handle: '@demo'\noutput_dir: output/demo\nenabled: true\n",
        encoding="utf-8")
    a = create_app(config_dir=cfg, db_path=tmp_path / "x.sqlite", scheduler=False)
    body = a.test_client().get("/channels/demo-tr/edit").data.decode("utf-8")
    assert "stresDurumu" in body, "seçici yok"
    assert "en uzun" in body.lower() or "en kötü" in body.lower()
