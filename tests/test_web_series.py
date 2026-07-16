"""Seri paneli: otomasyon KENDİNİ AÇIKLAMALI.

Seri mimarisi kurulduğunda bölümler yalnız veritabanında ve logda vardı. Kullanıcı
hangi bölümde olduğunu, arkın nerede olduğunu, SIRADAKİ bölümün neyi anlatacağını ya
da zincirin kopup kopmadığını hiçbir yerden göremiyordu. Görünmeyen bir otomasyon,
güvenilemeyen bir otomasyondur.

Bu sayfanın merkezindeki soru: BİR SONRAKİ KOŞU NE ÜRETECEK?
"""
import pytest

from short_bot.db import init_db, record_episode
from short_bot.web import create_app

_CH = """slug: seri
name: Seri Kanal
keywords: [bilim]
language: tr
schedule_cron: "0 10 * * *"
duration_s: 40
min_score: 7.0
max_candidates_per_run: 3
max_age_hours: 24
template: stat-hero
colors: {primary: '#0a2540', accent: '#2de2e6', bg_gradient: ['#0A2540', '#04121F']}
handle: '@seri'
output_dir: output/seri
enabled: false
content_source: generator
generator: {topic: 'ilginç bilgiler'}
reel:
  enabled: true
  voice_id: v1
  series_enabled: true
  series_title: Bilinmeyen Tarih
  series_arc_length: 3
  arc_mode: chain
"""

_KAPALI = _CH.replace("series_enabled: true", "series_enabled: false")
_PLANLI = _CH.replace("arc_mode: chain", "arc_mode: planned")


def _app(tmp_path, yaml_text=_CH):
    cfg = tmp_path / "config"; (cfg / "channels").mkdir(parents=True)
    (cfg / "settings.yaml").write_text(
        "ffmpeg_path: ffmpeg\nclaude_cli_path: claude\nplaywright_browser: chromium\n"
        "web: {host: 127.0.0.1, port: 5005}\nfuzzy_dedup_threshold: 0.85\nlog_level: INFO\n"
        "claude_models: {dna: opus, default: haiku}\n", encoding="utf-8")
    (cfg / "channels" / "seri.yaml").write_text(yaml_text, encoding="utf-8")
    db = tmp_path / "db.sqlite"
    init_db(db)
    app = create_app(config_dir=cfg, db_path=db, templates_dir=tmp_path / "t",
                     music_root=tmp_path, cache_dir=tmp_path, lock_dir=tmp_path,
                     logs_dir=tmp_path, output_root=tmp_path,
                     secrets_path=tmp_path / "secrets.yaml", scheduler=False)
    return app, db


@pytest.fixture
def app(tmp_path):
    return _app(tmp_path)


def test_bos_seri_sayfasi_acilir(app):
    a, _ = app
    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "Henüz bölüm üretilmedi" in body
    # Boş seride bile SIRADAKİ bölüm gösterilmeli: #1, bankadan konu
    assert "BİLİNMEYEN TARİH #1" in body
    assert "konu bankasından" in body


def test_SIRADAKI_bolumun_KONUSU_uretimden_ONCE_gorunur(app):
    """Sayfanın asıl cevabı. Üretim başladıktan sonra öğrenmek geç kalmaktır."""
    a, db = app
    record_episode(init_db(db), "seri", episode_no=1, arc_pos=1,
                   topic="Paslı benekli kediler",
                   open_loop="Ev kedilerinin işitmesinin avlanmadaki rolü")
    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "SIRADAKİ" in body
    assert "BİLİNMEYEN TARİH #2" in body
    assert "Ev kedilerinin işitmesinin avlanmadaki rolü" in body
    assert "önceki bölümün bıraktığı" in body or "kapıdan geliyor" in body


def test_takas_cipi_ARTIK_gosterilmez(app):
    # Beğeni/abone istekleri KALDIRILDI (2026-07-16, kullanıcı kararı) — seri
    # sayfası rozet/bölüm bilgisini gösterir ama ABONE OL çipi önizlemesi yok.
    a, db = app
    record_episode(init_db(db), "seri", episode_no=7, arc_pos=1, topic="x",
                   open_loop="bir kapı ve devamı")
    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "ABONE OL" not in body
    assert "Abone çipi" not in body


def test_gecmis_bolumler_ve_KAPILARI_listelenir(app):
    a, db = app
    eng = init_db(db)
    record_episode(eng, "seri", episode_no=1, arc_pos=1, topic="Birinci konu",
                   open_loop="Birinci kapı")
    record_episode(eng, "seri", episode_no=2, arc_pos=2, topic="Birinci kapı",
                   open_loop="İkinci kapı")
    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "Birinci konu" in body and "Birinci kapı" in body
    assert "#1" in body and "#2" in body


def test_kapisiz_bolum_ISARETLENIR(app):
    """Kapı yoksa ark orada bitmiş demektir — kullanıcı bunu görmeli."""
    a, db = app
    record_episode(init_db(db), "seri", episode_no=3, arc_pos=2, topic="Konu",
                   open_loop="")
    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "kapı yok" in body
    assert "konu bankasından" in body, "zincir kopuksa sıradaki konu bankadan gelmeli"


def test_ark_dolunca_zincir_KESILIR_ve_bankaya_donulur(app):
    """Zincir uzadıkça konu nişten sürüklenir → ark dolunca taze konu bankadan gelir."""
    a, db = app
    eng = init_db(db)
    for i in (1, 2, 3):
        record_episode(eng, "seri", episode_no=i, arc_pos=i, topic="k",
                       open_loop="bir kapı ve devamı")
    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "Zincir kapalı" in body
    assert "konu bankasından" in body
    assert "BİLİNMEYEN TARİH #4" in body, "numara devam etmeli"


def test_ZINCIRI_KES_dugmesi_calisir(app):
    """Zincir konudan sapabiliyor (sapma birikimli). Kesecek bir düğme olmadan
    tek çare YAML düzenlemek olurdu."""
    from short_bot.db import last_episode
    a, db = app
    eng = init_db(db)
    record_episode(eng, "seri", episode_no=5, arc_pos=2, topic="k",
                   open_loop="Saçmalayan bir kapı")

    r = a.test_client().post("/channels/seri/series/break-arc")
    assert r.status_code in (200, 302)

    son = last_episode(eng, "seri")
    assert son["open_loop"] == "", "kapı temizlenmedi → zincir sürüyor"
    assert son["episode_no"] == 5, "BÖLÜM NUMARASI korunmalı (feed kimliği delinmemeli)"


def test_zincir_kesilince_siradaki_bankadan_alir(app):
    a, db = app
    record_episode(init_db(db), "seri", episode_no=5, arc_pos=2, topic="k",
                   open_loop="Saçmalayan bir kapı")
    c = a.test_client()
    c.post("/channels/seri/series/break-arc")
    body = c.get("/channels/seri/series").data.decode("utf-8")
    assert "konu bankasından" in body
    assert "BİLİNMEYEN TARİH #6" in body, "numara devam etmeli"


def test_seri_kapaliysa_aciklama_gosterilir(tmp_path):
    a, _ = _app(tmp_path, _KAPALI)
    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "Seri modu kapalı" in body
    assert "takas" in body, "kullanıcı NEDEN açması gerektiğini anlamalı"


# ---------------------------------------------------------------------------
# KISIR DÖNGÜ (gerçek kullanıcı şikâyeti): "Seri" düğmesi yalnız seri AÇIKKEN
# görünüyordu. Yani açmak için sayfaya gitmen gerekiyordu, sayfaya gitmek için de
# açık olması. Kapalı sayfa artık KENDİNİ AÇTIRIR.
# ---------------------------------------------------------------------------

def test_kapali_sayfa_KENDINI_ACTIRIR(tmp_path):
    a, _ = _app(tmp_path, _KAPALI)
    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "/series/enable" in body, "kapalı sayfada açma düğmesi yok → kısır döngü"
    assert "Seri modunu aç" in body


def test_AC_dugmesi_seriyi_gercekten_acar(tmp_path, monkeypatch):
    """YAML'a yazmalı — yoksa düğme hiçbir şey yapmamış olur."""
    from short_bot.config import load_channel
    a, _ = _app(tmp_path, _KAPALI)
    cfg_dir = a.config["SHORTBOT_CONFIG_DIR"] / "channels" / "seri.yaml"

    r = a.test_client().post("/channels/seri/series/enable")
    assert r.status_code in (200, 302)

    cfg = load_channel(cfg_dir)
    assert cfg.reel.series_enabled is True
    assert cfg.reel.series_title, "başlık yoksa DNA'dan önerilmeliydi"

    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "Seri modu kapalı" not in body


def test_ac_dugmesi_MEVCUT_basligi_ezmez(tmp_path):
    from short_bot.config import load_channel
    yaml_text = _KAPALI  # series_title: Bilinmeyen Tarih (dolu)
    a, _ = _app(tmp_path, yaml_text)
    a.test_client().post("/channels/seri/series/enable")
    cfg = load_channel(a.config["SHORTBOT_CONFIG_DIR"] / "channels" / "seri.yaml")
    assert cfg.reel.series_title == "Bilinmeyen Tarih"


def test_kanal_kartinda_seri_dugmesi_SERI_KAPALIYKEN_DE_var(app):
    """Düğmeyi gizlemek, özelliği KEŞFEDİLEMEZ yapıyordu."""
    a, _ = app
    body = a.test_client().get("/channels").data.decode("utf-8")
    assert "/series" in body, "kanal kartında Seri bağlantısı yok"


# ---------------------------------------------------------------------------
# TOHUM SEÇİMİ. Ark ancak TOHUMU kadar iyidir: gerçek koşuda bankanın EN YENİ kaydı
# kanalın nişinden uzaktı ("vücudun onarım gücü" kanalına SAKIZ EFSANESİ arkı çıktı)
# ve planlayıcı onu sadakatle genişletti. Tohumu kullanıcı seçebilmeli.
# ---------------------------------------------------------------------------

def test_banka_konulari_TOHUM_olarak_listelenir(planli):
    from short_bot.db import insert_bank_topics
    a, db = planli
    insert_bank_topics(init_db(db), "seri", [
        {"topic": "Kirik kemik nasil kaynar", "views": 1, "subs": 1},
        {"topic": "Karaciger neden yenilenir", "views": 1, "subs": 1}])
    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "Kirik kemik nasil kaynar" in body
    assert "Karaciger neden yenilenir" in body
    assert "Ark ancak" in body, "tohumun önemi kullanıcıya söylenmeli"


def test_ELLE_YAZILAN_tohum_banka_konusunu_KULLANILDI_isaretlemez(planli, monkeypatch):
    """Bankadan seçip sonra elle yazarsan, eski id kalırsa YANLIŞ konu düşerdi."""
    import short_bot.web.routes.series as S
    from short_bot.db import all_bank_topics, insert_bank_topics
    a, db = planli
    eng = init_db(db)
    insert_bank_topics(eng, "seri", [{"topic": "Banka konusu", "views": 1, "subs": 1}])
    bid = all_bank_topics(eng, "seri")[0]["id"]

    # LLM'i devre dışı bırak: planlamanın kendisi bu testin konusu değil
    monkeypatch.setattr(S, "_llm_call", lambda: None)
    a.test_client().post("/channels/seri/series/plan-arc",
                         data={"seed_topic": "Kendi yazdigim tohum", "bank_id": ""})
    kayit = next(r for r in all_bank_topics(eng, "seri") if r["id"] == bid)
    assert kayit["status"] == "active", "elle yazılan tohum banka konusunu düşürdü"


def test_TURKCE_tohum_bozulmadan_kaydedilir(planli, monkeypatch):
    """Tohum konu Türkçe karakterlerle bozulmadan DB'ye ulaşmalı.

    Ark planlayıcının gördüğü METİN budur; 'Kırık' yerine 'K?r?k' giden bir tohum
    LLM'i yanıltır ve ark bambaşka bir yere gider.
    """
    import short_bot.reel_arc as A
    import short_bot.web.routes.series as S
    from short_bot.db import draft_arc

    a, db = planli
    tohum = "Kırık bir kemik vücutta nasıl kendi kendine kaynar"

    class _LC:
        claude_path = "x"; model = "m"; backend = "b"; api_key = None

    monkeypatch.setattr(S, "_llm_call", lambda: _LC())
    monkeypatch.setattr(A, "run_json", lambda *ar, **kw: A.ArcPlan(
        title="Kırık Kemik", episodes=[
            A.ArcEpisode(topic="Birinci bolum konusu burada", promise=""),
            A.ArcEpisode(topic="Ikinci bolum konusu burada", promise="vaat")]))

    a.test_client().post("/channels/seri/series/plan-arc",
                         data={"seed_topic": tohum, "bank_id": ""})
    import time
    for _ in range(50):                     # planlama daemon thread'de koşuyor
        d = draft_arc(init_db(db), "seri")
        if d:
            break
        time.sleep(0.1)
    assert d is not None, "taslak hiç oluşmadı"
    assert d["seed_topic"] == tohum, f"tohum bozulmuş: {d['seed_topic']!r}"
    assert d["title"] == "Kırık Kemik"


def test_rozet_onizlemesi_TURKCE_buyuk_harf(tmp_path):
    """Jinja'nın |upper'ı 'Bilim' → 'BILIM' yapar. Rozet bu hatayı yapamaz."""
    a, _ = _app(tmp_path, _KAPALI.replace("name: Seri Kanal", "name: Bilim Tarihi"))
    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "BİLİM #1" in body
    assert "BILIM #1" not in body


def test_olmayan_kanal_404(app):
    a, _ = app
    assert a.test_client().get("/channels/yok/series").status_code == 404


# ---------------------------------------------------------------------------
# PLANLI ARK: plan ONAYDAN ÖNCE görünür, onaysız üretilmez.
# ---------------------------------------------------------------------------

_ARK = [{"topic": "En kucuk vahsi kedi", "promise": ""},
        {"topic": "Kedi kulagindaki otuz iki kas", "promise": "Kulak sirri"},
        {"topic": "Avlanma basari orani", "promise": "Avlanma sirri"}]


@pytest.fixture
def planli(tmp_path):
    return _app(tmp_path, _PLANLI)


def test_TASLAK_ONAYDAN_ONCE_TAMAMEN_gorunur(planli):
    """Kullanıcı arkın NEREYE GİTTİĞİNİ üretim başlamadan görmeli."""
    from short_bot.db import create_arc
    a, db = planli
    create_arc(init_db(db), "seri", title="Kedilerin Gizli Biyolojisi",
               seed_topic="kediler", plan=_ARK)
    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "ONAY BEKLİYOR" in body
    assert "Kedilerin Gizli Biyolojisi" in body
    for e in _ARK:
        assert e["topic"] in body, f"plan kalemi görünmüyor: {e['topic']}"
    assert "Onaylamadan hiçbir bölüm üretilmez" in body


def test_ONAYSIZ_taslak_SIRADAKI_olarak_gosterilmez(planli):
    """Taslak sıradaki gibi görünürse kullanıcı onaylandığını sanır."""
    from short_bot.db import create_arc
    a, db = planli
    create_arc(init_db(db), "seri", title="Taslak", seed_topic="t", plan=_ARK)
    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "Onaylı ark yok" in body


def test_ONAYLA_dugmesi_arki_uretime_alir(planli):
    from short_bot.db import active_arc, create_arc
    a, db = planli
    eng = init_db(db)
    aid = create_arc(eng, "seri", title="Ark", seed_topic="t", plan=_ARK)

    r = a.test_client().post(f"/channels/seri/series/arcs/{aid}/approve")
    assert r.status_code in (200, 302)
    assert active_arc(eng, "seri") is not None

    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "Konu onaylı plandan geliyor" in body
    assert _ARK[0]["topic"] in body
    assert "Aktif ark" in body


def test_SIL_dugmesi_taslagi_atar(planli):
    from short_bot.db import create_arc, draft_arc
    a, db = planli
    eng = init_db(db)
    aid = create_arc(eng, "seri", title="Ark", seed_topic="t", plan=_ARK)
    a.test_client().post(f"/channels/seri/series/arcs/{aid}/discard")
    assert draft_arc(eng, "seri") is None


def test_aktif_arkta_ILERLEME_gorunur(planli):
    from short_bot.db import advance_arc, approve_arc, create_arc
    a, db = planli
    eng = init_db(db)
    aid = create_arc(eng, "seri", title="Ark", seed_topic="t", plan=_ARK)
    approve_arc(eng, aid)
    advance_arc(eng, aid)

    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "1/3 üretildi" in body
    assert "sıradaki" in body
    assert _ARK[1]["topic"] in body, "sıradaki plan kalemi gösterilmiyor"


def test_ONAYLI_ARK_YOKSA_kullanici_UYARILIR(planli):
    """Planlı modda onaysız koşu seriyi ilerletmez — bu sessizce olmamalı."""
    a, _ = planli
    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "Onaylı ark yok" in body
    assert "Yeni ark planla" in body


def test_zincir_modunda_ark_planlama_dugmesi_YOK(app):
    a, _ = app     # arc_mode: chain
    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "Yeni ark planla" not in body


def test_baslik_yoksa_DNA_onerisi_sunulur(tmp_path):
    a, _ = _app(tmp_path, _PLANLI.replace("series_title: Bilinmeyen Tarih",
                                          "series_title: ''"))
    body = a.test_client().get("/channels/seri/series").data.decode("utf-8")
    assert "Seri başlığı yok" in body
    assert "DNA'dan öner" in body
