"""Boru hattında ARK ZİNCİRİ: bir bölümün açtığı kapı, sonrakinin KONUSU olmalı.

Saf fonksiyonların doğruluğu yetmez — asıl risk BAĞLANTIDA. Bölüm planlanıyor mu,
kapı forced_topic'e geçiyor mu, üretim başarılıysa kaydediliyor mu, BAŞARISIZSA
numara tüketiliyor mu? Feed'de #47'den #49'a atlayan bir seri, serinin gerçek
olduğuna dair tek somut kanıtı çürütür.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from short_bot.config import (ChannelConfig, GeneratorConfig, ReelConfig, Settings)
from short_bot.db import init_db, last_episode
from short_bot.dna import DnaFonts, DnaPalette, DnaSpec, DnaTone
from short_bot.generator import GeneratorResult
from short_bot.pipeline import run_pipeline


def _settings():
    return Settings(ffmpeg_path="ffmpeg", claude_cli_path="claude",
                    playwright_browser="chromium", web_host="127.0.0.1",
                    web_port=5005, fuzzy_dedup_threshold=0.85, log_level="INFO",
                    claude_models={"dna": "opus", "default": "haiku"})


def _dna():
    return DnaSpec(
        archetype="stat-hero",
        palette=DnaPalette(primary="#000000", accent="#ffffff",
                           bg_gradient=["#000000", "#111111"],
                           body_bg=["#000000", "#111111"]),
        fonts=DnaFonts(headline="Anton", body="Inter"),
        tone=DnaTone(voice="merakli", style="kisa", forbidden=[],
                     sentence_max_words=12, body_max_chars=200,
                     headline_style_hint="iki satir"),
        category_icon="🔬", persona_summary="Sok anlar.")


def _channel(tmp_path, *, arc_max=3, arc_mode="chain"):
    return ChannelConfig(
        slug="seri-kanal", name="Seri", keywords=[], rss_locale="hl=tr",
        schedule_cron="*", duration_s=40, min_score=0.0,
        max_candidates_per_run=1, template="stat-hero",
        colors={"primary": "#000", "accent": "#fff", "bg_gradient": ["#000", "#111"]},
        handle="@seri", output_dir=str(tmp_path / "out"), enabled=True,
        language="tr", dna=_dna(), script_model="sonnet",
        content_source="generator",
        generator=GeneratorConfig(topic="ilginc bilgiler", forbidden_lookback=10,
                                  max_retries=2, fuzzy_threshold=0.85),
        reel=ReelConfig(enabled=True, voice_id="v1", series_enabled=True,
                        series_title="Bilinmeyen", series_arc_length=arc_max,
                        arc_mode=arc_mode),
    )


def _result(text):
    return GeneratorResult(
        text=text, topic_tag="bilim",
        script={"header_top": "A", "header_bottom": "B", "photo_overlay": "C",
                "body_paragraph": f"{text} Bu konunun devami boyle gelisiyor.",
                "highlights": [], "category": "bilim", "mood": "neutral"},
        image_keywords=["science"])


class _Narr:
    """produce_reel_video'nun on_narration ile geri verdiği şey (yalnız open_loop lazım)."""
    def __init__(self, open_loop):
        self.open_loop = open_loop


def _kos(cfg, tmp_path, db, *, konu, kapi, patlat=False):
    """Tek bir üretim koştur; hangi konunun ZORLANDIĞINI ve kaydı döndür."""
    gorulen = {}

    def _sahte_reel(**kw):
        gorulen["episode"] = kw.get("episode")
        gorulen["topic"] = kw["topic"]
        if patlat:
            raise RuntimeError("montaj patladı")
        on = kw.get("on_narration")
        if on is not None:
            on(_Narr(kapi))
        Path(kw["out_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(kw["out_path"]).write_bytes(b"mp4")
        return Path(kw["out_path"])

    logs = tmp_path / "logs"; logs.mkdir(exist_ok=True)
    with patch("short_bot.pipeline.generate_quote", return_value=_result(konu)), \
         patch("short_bot.pipeline._reel_produce_or_none", side_effect=_sahte_reel):
        r = run_pipeline(channel=cfg, settings=_settings(), db_path=db,
                         music_root=tmp_path, templates_dir=tmp_path,
                         cache_dir=tmp_path / "cache", lock_dir=tmp_path / "locks",
                         logs_dir=logs, trigger="test")
    return r, gorulen


def test_ilk_bolum_bir_numara_ve_kapi_kaydedilir(tmp_path):
    cfg = _channel(tmp_path)
    db = tmp_path / "db.sqlite"
    r, g = _kos(cfg, tmp_path, db, konu="fener baligi", kapi="O isigi ureten sey ne?")
    assert r.status == "success"
    assert g["episode"].episode_no == 1
    assert g["episode"].continue_from == "", "ilk bölümde ödenecek söz yok"

    kayit = last_episode(init_db(db), "seri-kanal")
    assert kayit["episode_no"] == 1
    assert kayit["open_loop"] == "O isigi ureten sey ne?"


def test_IKINCI_bolumun_KONUSU_oncekinin_KAPISIDIR(tmp_path):
    """ARKIN TA KENDİSİ. Bu geçmezse seri diye bir şey yok — sadece numaralı videolar."""
    cfg = _channel(tmp_path)
    db = tmp_path / "db.sqlite"
    _kos(cfg, tmp_path, db, konu="fener baligi", kapi="O isigi ureten bakteri hangisi?")

    # generate_quote'a NE gönderildiğini de görelim: forced_topic zincirden gelmeli
    _, g = _kos(cfg, tmp_path, db, konu="O isigi ureten bakteri hangisi?",
                kapi="Peki o bakteri oraya nasil gitti?")
    assert g["episode"].episode_no == 2
    assert g["episode"].arc_pos == 2
    assert g["episode"].continue_from == "O isigi ureten bakteri hangisi?", (
        "2. bölüm önceki bölümün sözünü ödemiyor → takas kırık")


def test_ark_dolunca_zincir_kesilir(tmp_path):
    cfg = _channel(tmp_path, arc_max=2)
    db = tmp_path / "db.sqlite"
    _kos(cfg, tmp_path, db, konu="Birinci bolumun konusu", kapi="Birinci kapi acildi")
    _kos(cfg, tmp_path, db, konu="Birinci kapi acildi", kapi="Ikinci kapi")
    _, g = _kos(cfg, tmp_path, db, konu="Bankadan gelen taze konu", kapi="Ucuncu kapi")
    assert g["episode"].episode_no == 3, "numara devam etmeli"
    assert g["episode"].arc_pos == 1, "yeni ark"
    assert g["episode"].continue_from == "", "zincir kesildi → bankadan taze konu"


def test_BASARISIZ_uretim_bolum_numarasi_TUKETMEZ(tmp_path):
    """Feed'de #47'den #49'a atlayan bir seri, gerçek olduğunun kanıtını çürütür."""
    cfg = _channel(tmp_path)
    db = tmp_path / "db.sqlite"
    _kos(cfg, tmp_path, db, konu="Birinci bolumun konusu", kapi="Birinci kapi acildi")

    r, _ = _kos(cfg, tmp_path, db, konu="Birinci kapi acildi", kapi="Ikinci kapi", patlat=True)
    assert r.status != "success"
    assert last_episode(init_db(db), "seri-kanal")["episode_no"] == 1, (
        "başarısız üretim bölüm numarasını tüketmiş")

    _, g = _kos(cfg, tmp_path, db, konu="Birinci kapi acildi", kapi="Ikinci kapi")
    assert g["episode"].episode_no == 2, "numara delik açılmadan devam etmeli"


def test_seri_kapaliysa_bolum_plani_kurulmaz(tmp_path):
    cfg = _channel(tmp_path)
    cfg.reel.series_enabled = False
    db = tmp_path / "db.sqlite"
    _, g = _kos(cfg, tmp_path, db, konu="Serisiz normal konu", kapi="onemsiz")
    assert g["episode"] is None
    assert last_episode(init_db(db), "seri-kanal") is None


def test_kapi_acilmadiysa_sonraki_bolum_bankadan_konu_alir(tmp_path):
    cfg = _channel(tmp_path)
    db = tmp_path / "db.sqlite"
    _kos(cfg, tmp_path, db, konu="Kapisiz kalan bolum", kapi="")     # LLM kapı açmadı
    _, g = _kos(cfg, tmp_path, db, konu="Bankadan gelen taze konu", kapi="Yeni kapi")
    assert g["episode"].episode_no == 2
    assert g["episode"].continue_from == ""
    assert g["topic"] == "Bankadan gelen taze konu", "kapı yokken konu zincirden gelmemeli"


# ---------------------------------------------------------------------------
# PLANLI ARK: konu ve SIRADAKİ konu plandan gelir → LLM cliffhanger'ı uydurmaz.
# ---------------------------------------------------------------------------

_ARK = [{"topic": "Birinci bolum: en kucuk vahsi kedi", "promise": ""},
        {"topic": "Ikinci bolum: kedi kulagindaki otuz iki kas", "promise": "Kulak sirri"},
        {"topic": "Ucuncu bolum: avlanma basari orani", "promise": "Avlanma sirri"}]


def _onayli_ark(db, plan=None):
    from short_bot.db import approve_arc, create_arc
    eng = init_db(db)
    aid = create_arc(eng, "seri-kanal", title="Kedilerin Gizli Biyolojisi",
                     seed_topic="kediler", plan=plan or _ARK)
    approve_arc(eng, aid)
    return aid


def test_PLANLI_arkta_konu_PLANDAN_gelir(tmp_path):
    cfg = _channel(tmp_path, arc_mode="planned")
    db = tmp_path / "db.sqlite"
    _onayli_ark(db)
    _, g = _kos(cfg, tmp_path, db, konu=_ARK[0]["topic"], kapi="onemsiz")
    assert g["topic"] == _ARK[0]["topic"], "konu plandan gelmedi"
    ep = g["episode"]
    assert ep.is_planned and ep.arc_total == 3 and ep.arc_pos == 1
    assert ep.arc_title == "Kedilerin Gizli Biyolojisi"
    # SIRADAKİ konu DAYATILIR → LLM cliffhanger'ı uydurmaz, söyler
    assert ep.next_topic == _ARK[1]["topic"]


def test_PLAN_sirayla_tuketilir(tmp_path):
    cfg = _channel(tmp_path, arc_mode="planned")
    db = tmp_path / "db.sqlite"
    _onayli_ark(db)
    for i in range(3):
        _, g = _kos(cfg, tmp_path, db, konu=_ARK[i]["topic"], kapi="k")
        assert g["topic"] == _ARK[i]["topic"], f"{i + 1}. bölüm planı takip etmiyor"
        assert g["episode"].arc_pos == i + 1


def test_SON_bolumde_siradaki_konu_YOK(tmp_path):
    """Plan bitti → ödenmemiş vaat bırakılmaz (ama seri devam eder)."""
    cfg = _channel(tmp_path, arc_mode="planned")
    db = tmp_path / "db.sqlite"
    _onayli_ark(db)
    for i in range(2):
        _kos(cfg, tmp_path, db, konu=_ARK[i]["topic"], kapi="k")
    _, g = _kos(cfg, tmp_path, db, konu=_ARK[2]["topic"], kapi="")
    assert g["episode"].next_topic == ""
    assert g["episode"].is_arc_finale


def test_BASARISIZ_uretim_PLANI_TUKETMEZ(tmp_path):
    """Başarısız bir koşu planı tüketirse o bölüm hiç üretilmemiş olur → planda delik."""
    from short_bot.db import active_arc
    cfg = _channel(tmp_path, arc_mode="planned")
    db = tmp_path / "db.sqlite"
    _onayli_ark(db)
    eng = init_db(db)

    r, _ = _kos(cfg, tmp_path, db, konu=_ARK[0]["topic"], kapi="k", patlat=True)
    assert r.status != "success"
    assert active_arc(eng, "seri-kanal")["produced"] == 0, "plan tüketilmiş"

    _, g = _kos(cfg, tmp_path, db, konu=_ARK[0]["topic"], kapi="k")
    assert g["topic"] == _ARK[0]["topic"], "aynı bölüm yeniden denenmemiş"
    assert active_arc(eng, "seri-kanal")["produced"] == 1


def test_ONAYSIZ_taslak_URETILMEZ(tmp_path):
    """Taslak üretime girerse onay mekanizmasının hiçbir anlamı kalmaz."""
    from short_bot.db import create_arc
    cfg = _channel(tmp_path, arc_mode="planned")
    db = tmp_path / "db.sqlite"
    create_arc(init_db(db), "seri-kanal", title="Taslak", seed_topic="t", plan=_ARK)

    _, g = _kos(cfg, tmp_path, db, konu="Bankadan gelen taze konu", kapi="k")
    assert g["topic"] == "Bankadan gelen taze konu", "ONAYSIZ plan üretime girdi"
    assert not g["episode"].is_planned


# ---------------------------------------------------------------------------
# BAĞIMSIZ VİDEO: seri açık ama bu video seriyi İLERLETMEZ.
#
# Seri bölümü "#2 YARIN" diye söz veriyor. Günde 3 bölüm üretilirse 3 bölümlük ark
# BİR GÜNDE biter ve #2 aynı gün yayınlanır — söz YALAN olur, abone takası çöker.
# ---------------------------------------------------------------------------

def _kos_standalone(cfg, tmp_path, db, *, konu):
    gorulen = {}

    def _sahte_reel(**kw):
        gorulen["episode"] = kw.get("episode")
        gorulen["topic"] = kw["topic"]
        on = kw.get("on_narration")
        if on is not None:
            on(_Narr("bir kapi"))
        Path(kw["out_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(kw["out_path"]).write_bytes(b"mp4")
        return Path(kw["out_path"])

    logs = tmp_path / "logs"; logs.mkdir(exist_ok=True)
    with patch("short_bot.pipeline.generate_quote", return_value=_result(konu)), \
         patch("short_bot.pipeline._reel_produce_or_none", side_effect=_sahte_reel):
        r = run_pipeline(channel=cfg, settings=_settings(), db_path=db,
                         music_root=tmp_path, templates_dir=tmp_path,
                         cache_dir=tmp_path / "cache", lock_dir=tmp_path / "locks",
                         logs_dir=logs, trigger="autopilot", standalone=True)
    return r, gorulen


def test_BAGIMSIZ_video_BOLUM_URETMEZ(tmp_path):
    cfg = _channel(tmp_path, arc_mode="planned")
    db = tmp_path / "db.sqlite"
    _onayli_ark(db)

    r, g = _kos_standalone(cfg, tmp_path, db, konu="Bankadan bagimsiz bir konu")
    assert r.status == "success"
    assert g["episode"] is None, "bağımsız videoda bölüm planlandı → seri delinir"


def test_BAGIMSIZ_video_ARKI_TUKETMEZ(tmp_path):
    """Ark tüketilirse 3 bölümlük ark bir günde biter ve '#2 yarın' sözü bozulur."""
    from short_bot.db import active_arc
    cfg = _channel(tmp_path, arc_mode="planned")
    db = tmp_path / "db.sqlite"
    _onayli_ark(db)
    eng = init_db(db)

    _kos_standalone(cfg, tmp_path, db, konu="Bankadan bagimsiz bir konu")
    assert active_arc(eng, "seri-kanal")["produced"] == 0, "bağımsız video arkı tüketti"


def test_BAGIMSIZ_video_BOLUM_KAYDETMEZ(tmp_path):
    from short_bot.db import last_episode
    cfg = _channel(tmp_path, arc_mode="planned")
    db = tmp_path / "db.sqlite"
    _onayli_ark(db)

    _kos_standalone(cfg, tmp_path, db, konu="Bankadan bagimsiz bir konu")
    assert last_episode(init_db(db), "seri-kanal") is None, \
        "bağımsız video bölüm numarası tüketti → feed'de delik"


def test_BAGIMSIZ_video_KONUSU_bankadan_gelir(tmp_path):
    """Planlı ark varken bile bağımsız video plandan konu ALMAMALI."""
    cfg = _channel(tmp_path, arc_mode="planned")
    db = tmp_path / "db.sqlite"
    _onayli_ark(db)

    _, g = _kos_standalone(cfg, tmp_path, db, konu="Bankadan bagimsiz bir konu")
    assert g["topic"] == "Bankadan bagimsiz bir konu"
    assert g["topic"] != _ARK[0]["topic"]


def test_standalone_KAPALIYKEN_seri_normal_calisir(tmp_path):
    """Geriye uyum: standalone=False iken bölüm yine üretilmeli."""
    cfg = _channel(tmp_path, arc_mode="planned")
    db = tmp_path / "db.sqlite"
    _onayli_ark(db)
    _, g = _kos(cfg, tmp_path, db, konu=_ARK[0]["topic"], kapi="k")
    assert g["episode"] is not None and g["episode"].episode_no == 1


def test_ONAYLI_ARK_YOKSA_uretim_DURMAZ(tmp_path):
    """Duran bir otomasyon, sapmış bir otomasyondan kötüdür — bankadan tek konu üretir."""
    cfg = _channel(tmp_path, arc_mode="planned")
    db = tmp_path / "db.sqlite"
    r, g = _kos(cfg, tmp_path, db, konu="Bankadan gelen taze konu", kapi="k")
    assert r.status == "success"
    assert g["episode"].episode_no == 1
    assert not g["episode"].is_planned

