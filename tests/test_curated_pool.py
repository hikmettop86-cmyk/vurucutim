"""Kürate havuzu: dedup anahtarı + havuz CRUD (insert/list/mark/count) — ağsız."""
from short_bot.curated_pool import (POOL_MAX, clip_key, count_pending, list_pool,
                                    mark_pool, pool_counts, pool_keys, row_to_gem)
from short_bot.db import init_db, pooled_gems


def test_clip_key_consistency():
    # v.redd.it → id; query stripped → aynı klip aynı anahtar
    assert clip_key("https://v.redd.it/abc123/CMAF_720.mp4?x=1") == "vreddit:abc123"
    assert clip_key("https://v.redd.it/abc123/DASH.mp4") == "vreddit:abc123"
    # diğer domain → query'siz url
    assert clip_key("https://streamable.com/xyz?t=2") == "https://streamable.com/xyz"
    assert clip_key("") == ""


def _insert(eng, channel, clip, **kw):
    with eng.begin() as c:
        c.execute(pooled_gems.insert().values(
            channel=channel, clip_key=clip, video_url=kw.get("url", "https://v.redd.it/x/y.mp4"),
            title=kw.get("title", "t"), sub=kw.get("sub", "funny"), ups=kw.get("ups", 1000),
            score=kw.get("score", 8.0), tone="mizah", status=kw.get("status", "pending"),
            duration=kw.get("duration", 20)))


def test_pool_crud(tmp_path):
    eng = init_db(tmp_path / "pool.db")
    _insert(eng, "kaosdayi", "vreddit:a", score=9.0)
    _insert(eng, "kaosdayi", "vreddit:b", score=5.0)
    _insert(eng, "kaosdayi", "vreddit:c", status="produced")
    _insert(eng, "dayidiyorki", "vreddit:d")            # başka kanal

    # count_pending: kanal-bazlı, yalnız pending
    assert count_pending(eng, "kaosdayi") == 2
    assert count_pending(eng, "dayidiyorki") == 1

    # pool_keys: TÜM durumlar (üretilmiş dahil) — yeniden eklememek için
    assert pool_keys(eng, "kaosdayi") == {"vreddit:a", "vreddit:b", "vreddit:c"}

    # list_pool: pending, SKOR sıralı (a=9 önce, b=5 sonra)
    gems = list_pool(eng, "kaosdayi")
    assert [g["clip_key"] for g in gems] == ["vreddit:a", "vreddit:b"]

    # pool_counts: durum dağılımı
    counts = pool_counts(eng, "kaosdayi")
    assert counts.get("pending") == 2 and counts.get("produced") == 1

    # mark_pool: pending → skipped
    mark_pool(eng, gems[1]["id"], "skipped")
    assert count_pending(eng, "kaosdayi") == 1
    assert pool_counts(eng, "kaosdayi").get("skipped") == 1


def test_seen_memory(tmp_path):
    """Elenen-hafızası: mark_seen/seen_keys — per-kanal, OR IGNORE (tekrar sorun değil),
    boş clip_key no-op. auto_produce önceden elenen klibi bir daha indirmesin diye."""
    from short_bot.curated_pool import mark_seen, seen_keys

    eng = init_db(tmp_path / "s.db")
    mark_seen(eng, "kaosdayi", "vreddit:a", "watermark")
    mark_seen(eng, "kaosdayi", "vreddit:a", "watermark")   # tekrar → OR IGNORE (hata yok)
    mark_seen(eng, "kaosdayi", "vreddit:b", "off-tone")
    mark_seen(eng, "dayidiyorki", "vreddit:a", "produced")  # başka kanal ayrı
    mark_seen(eng, "kaosdayi", "", "x")                     # boş → no-op
    assert seen_keys(eng, "kaosdayi") == {"vreddit:a", "vreddit:b"}
    assert seen_keys(eng, "dayidiyorki") == {"vreddit:a"}
    assert seen_keys(eng, "yok") == set()


def test_row_to_gem_shape():
    row = {"video_url": "https://v.redd.it/x/y.mp4", "title": "başlık",
           "permalink": "https://reddit.com/r/x/1", "sub": "funny", "ups": 500,
           "comments": 10, "duration": 25, "width": 1080, "height": 1920, "orient": "DİKEY",
           "thumb": "https://t/img.jpg"}
    gem = row_to_gem(row)
    # produce_curated'ın beklediği zorunlu alanlar
    assert gem["video_url"] == row["video_url"]
    assert gem["title"] == "başlık" and gem["permalink"] == row["permalink"]
    assert gem["duration"] == 25 and gem["orient"] == "DİKEY"


def test_pool_max_is_sane():
    assert 10 <= POOL_MAX <= 200


def test_score_curiosity_drops_text_covers(monkeypatch):
    """drop_text: kapağında gömülü yazı/logo (has_text) olan gem SONUÇTAN atılır;
    drop_text=False iken kalır."""
    import short_bot.claude_cli as cc
    from short_bot.curated_rank import CuriosityScore, score_curiosity

    def _fake_run_json(prompt, schema, **kw):
        # başlıkta 'KIRLI' geçen kapak yazılı sayılsın
        return CuriosityScore(score=8, has_text=("KIRLI" in prompt))

    monkeypatch.setattr(cc, "run_json", _fake_run_json)

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    gems = [
        {"title": "TEMIZ klip", "ups": 1000, "thumb": "", "comments": 5,
         "orient": "DİKEY", "duration": 20},
        {"title": "KIRLI yazılı", "ups": 2000, "thumb": "", "comments": 5,
         "orient": "DİKEY", "duration": 20},
    ]
    out = score_curiosity(gems, vision_call=_V(), tone="mizah")
    titles = [g["title"] for g in out]
    assert "TEMIZ klip" in titles and "KIRLI yazılı" not in titles   # yazılı elendi

    out2 = score_curiosity(gems, vision_call=_V(), tone="mizah", drop_text=False)
    assert {g["title"] for g in out2} == {"TEMIZ klip", "KIRLI yazılı"}  # ikisi de kalır


def test_collect_pool_fail_open_when_vision_down(tmp_path, monkeypatch):
    """Vision skorlanamazsa (resolve çöker → vision None → tüm curiosity None) havuz SESSİZCE
    boş kalmasın: engagement sırasıyla fail-open aday eklenmeli (kullanıcı: 'no_candidates')."""
    from types import SimpleNamespace

    import short_bot.curated_pool as cp
    import short_bot.pipeline as pl
    import short_bot.reddit_gems as rg

    gems = [
        {"video_url": f"https://v.redd.it/g{i}/DASH.mp4", "title": f"klip{i}",
         "permalink": f"https://reddit.com/r/funny/{i}", "sub": "funny",
         "ups": 3000 - i * 100, "comments": 20, "duration": 20, "width": 1080,
         "height": 1920, "orient": "DİKEY", "thumb": ""}
        for i in range(5)
    ]
    monkeypatch.setattr(rg, "find_gems", lambda *a, **k: gems)
    monkeypatch.setattr(rg, "fetch_popular", lambda *a, **k: [])
    # resolve_ai_call ÇÖKER → vision None → score_curiosity hepsini curiosity=None yapar
    monkeypatch.setattr(pl, "resolve_ai_call",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("vision yok")))

    reel = SimpleNamespace(enabled=True, curated_tone="mizah", curated_min_ups=500,
                           curated_max_duration=90, subreddits=[], curated_time="month",
                           curated_include_popular=False)
    channel = SimpleNamespace(slug="kaosdayi", content_source="curated", reel=reel)
    added = cp.collect_pool(channel, settings=SimpleNamespace(ffmpeg_path="ffmpeg"),
                            secrets={"reddit_client_id": "x", "reddit_client_secret": "y"},
                            db_path=tmp_path / "pool.db")
    assert added > 0   # vision yok AMA fail-open → havuz boş kalmadı (eskiden 0'dı)


def test_auto_produce_duygu_fail_open_when_vision_down(tmp_path, monkeypatch):
    """DUYGU auto-üretim: vision skorlanamazsa (resolve çöker) sert eşik üretimi SESSİZCE
    engelliyordu (kullanıcı: 'no_candidates'). Fix: skorsuzsa engagement sırasıyla üret."""
    from types import SimpleNamespace

    import short_bot.curated_pipeline as cpl
    import short_bot.pipeline as pl
    import short_bot.reddit_gems as rg

    gems = [{"video_url": f"https://v.redd.it/d{i}/DASH.mp4", "title": f"kurtarma{i}",
             "permalink": f"https://reddit.com/r/aww/{i}", "sub": "aww",
             "ups": 5000 - i * 100, "comments": 30, "duration": 60, "orient": "DİKEY"}
            for i in range(3)]
    monkeypatch.setattr(rg, "find_gems", lambda *a, **k: gems)
    monkeypatch.setattr(pl, "resolve_ai_call",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("vision yok")))
    called = {}

    def fake_produce(gem, channel, **k):
        called["gem"] = gem
        return ("sid-1", tmp_path / "out.mp4")

    monkeypatch.setattr(cpl, "produce_curated", fake_produce)

    reel = SimpleNamespace(curated_tone="duygu", subreddits=[], curated_time="week",
                           curated_min_ups=500, curated_max_duration=90)
    channel = SimpleNamespace(slug="dayidiyorki", reel=reel)
    sid, path = cpl.auto_produce_curated(
        channel, settings=SimpleNamespace(ffmpeg_path="ffmpeg"),
        secrets={"reddit_client_id": "x", "reddit_client_secret": "y"},
        db_path=tmp_path / "db.sqlite", output_root=tmp_path, music_root=tmp_path,
        templates_dir=tmp_path)
    assert sid == "sid-1" and called   # vision yok AMA fail-open → üretim denendi (None,None DEĞİL)


def test_produce_curated_fail_closed_on_unverified_watermark(tmp_path, monkeypatch):
    """TEMİZLİK FAIL-CLOSED: watermark tespiti DOĞRULANAMAZSA (detect None) klip KULLANILMAZ →
    CuratedWatermarkError (short 968: None fail-open ile TikTok logolu klip geçmişti)."""
    from pathlib import Path
    from types import SimpleNamespace

    import pytest

    import short_bot.curated_clean as cc
    import short_bot.curated_pipeline as cpl
    import short_bot.pipeline as pl
    import short_bot.reddit_gems as rg
    import short_bot.tts.ai33_client as ai33
    from short_bot.config import AICall

    fake = AICall(backend="google_studio", model="m", api_key=None, claude_path="")
    monkeypatch.setattr(pl, "resolve_ai_call", lambda *a, **k: fake)   # vision non-None
    monkeypatch.setattr(ai33, "resolve_ai33_api_key", lambda *a, **k: "k")
    monkeypatch.setattr(rg, "download_clip",
                        lambda url, dest: (Path(dest).write_bytes(b"m"), Path(dest))[1])
    # detect DOĞRULAYAMADI → clean_if_needed (clip, None) döner
    monkeypatch.setattr(cc, "clean_if_needed", lambda clip, **k: (clip, None))

    reel = SimpleNamespace(enabled=True, curated_clean=True, persona="", curated_tone="mizah")
    channel = SimpleNamespace(slug="kaosdayi", language="tr", reel=reel)
    with pytest.raises(cpl.CuratedWatermarkError):
        cpl.produce_curated(
            {"video_url": "https://v.redd.it/x/DASH.mp4", "title": "t"}, channel,
            settings=SimpleNamespace(ffmpeg_path="ffmpeg", claude_cli_path="claude"),
            secrets={}, db_path=tmp_path / "db.sqlite", output_root=tmp_path,
            music_root=tmp_path, templates_dir=tmp_path)


def test_produce_curated_rejects_heavy_burned_text(tmp_path, monkeypatch):
    """GÖMÜLÜ-YAZI REDDİ: watermark temiz geçse bile klip altyazı/banner ile DOLUYSA
    (detect_heavy_text.heavy=True) reddedilir (short 968 'THIS IS JAPAN' + altyazılar)."""
    from pathlib import Path
    from types import SimpleNamespace

    import pytest

    import short_bot.curated_clean as cc
    import short_bot.curated_pipeline as cpl
    import short_bot.pipeline as pl
    import short_bot.reddit_gems as rg
    import short_bot.tts.ai33_client as ai33
    from short_bot.config import AICall
    from short_bot.curated_clean import HeavyText, WatermarkDetect

    fake = AICall(backend="google_studio", model="m", api_key=None, claude_path="")
    monkeypatch.setattr(pl, "resolve_ai_call", lambda *a, **k: fake)
    monkeypatch.setattr(ai33, "resolve_ai33_api_key", lambda *a, **k: "k")
    monkeypatch.setattr(rg, "download_clip",
                        lambda url, dest: (Path(dest).write_bytes(b"m"), Path(dest))[1])
    # watermark TEMİZ geçsin (present=False), banner yok, AMA gömülü-yazı DOLU
    monkeypatch.setattr(cc, "clean_if_needed",
                        lambda clip, **k: (clip, WatermarkDetect(present=False)))
    monkeypatch.setattr(cc, "detect_source_banner", lambda clip, **k: None)
    monkeypatch.setattr(cc, "detect_heavy_text",
                        lambda clip, **k: HeavyText(heavy=True, kinds=["subtitle", "banner"]))

    reel = SimpleNamespace(enabled=True, curated_clean=True, persona="", curated_tone="mizah")
    channel = SimpleNamespace(slug="kaosdayi", language="tr", reel=reel)
    with pytest.raises(cpl.CuratedWatermarkError):
        cpl.produce_curated(
            {"video_url": "https://v.redd.it/x/DASH.mp4", "title": "t"}, channel,
            settings=SimpleNamespace(ffmpeg_path="ffmpeg", claude_cli_path="claude"),
            secrets={}, db_path=tmp_path / "db.sqlite", output_root=tmp_path,
            music_root=tmp_path, templates_dir=tmp_path)


def test_produce_curated_rejects_mundane_clip(tmp_path, monkeypatch):
    """KALİTE KAPISI (short 992: 'hiç komik bir şey yok, çok zayıf'): watermark/banner/heavy-text
    TEMİZ ve tone-fit GEÇSE bile, klip storyboard'da SIRADAN/zayıfsa (judge_clip_quality
    engaging=False / düşük skor) reddedilir → oto-üretim sıradaki adaya geçer. tone-fit DOĞRU-ton'a
    bakar, GÜÇLÜ'ye değil; asıl güç-bariyeri budur (iç-şaka contagiouslaughter klibi)."""
    from pathlib import Path
    from types import SimpleNamespace

    import pytest

    import short_bot.curated_clean as cc
    import short_bot.curated_pipeline as cpl
    import short_bot.pipeline as pl
    import short_bot.reddit_gems as rg
    import short_bot.reel as reel_mod
    import short_bot.reel_narration as rn
    import short_bot.tts.ai33_client as ai33
    from short_bot.config import AICall
    from short_bot.curated_clean import ClipQuality, HeavyText, WatermarkDetect
    from short_bot.reel_narration import ToneFit

    fake = AICall(backend="google_studio", model="m", api_key=None, claude_path="")
    monkeypatch.setattr(pl, "resolve_ai_call", lambda *a, **k: fake)
    monkeypatch.setattr(ai33, "resolve_ai33_api_key", lambda *a, **k: "k")
    monkeypatch.setattr(rg, "download_clip",
                        lambda url, dest: (Path(dest).write_bytes(b"m"), Path(dest))[1])
    # temizlik kapıları TEMİZ geçsin
    monkeypatch.setattr(cc, "clean_if_needed",
                        lambda clip, **k: (clip, WatermarkDetect(present=False)))
    monkeypatch.setattr(cc, "detect_source_banner", lambda clip, **k: None)
    monkeypatch.setattr(cc, "detect_heavy_text", lambda clip, **k: HeavyText(heavy=False))
    # süre + tarif + tone-fit GEÇSİN (klip doğru tonda ve yeterince uzun)
    monkeypatch.setattr(reel_mod, "_clip_duration_s", lambda clip, *a, **k: 20.0)
    monkeypatch.setattr(reel_mod, "_describe_clip",
                        lambda clip, **k: "iki kadin mutfakta gulusuyor")
    monkeypatch.setattr(rn, "judge_tone_fit", lambda *a, **k: ToneFit(fits=True, reason=""))
    # AMA storyboard kalitesi ZAYIF → kalite kapısı reddetmeli (992: engaging=False, skor 3)
    monkeypatch.setattr(cc, "judge_clip_quality",
                        lambda clip, **k: ClipQuality(engaging=False, score=3,
                                                      reason="ic saka, kanca yok"))

    reel = SimpleNamespace(enabled=True, curated_clean=True, persona="", curated_tone="mizah")
    channel = SimpleNamespace(slug="kaosdayi", language="tr", reel=reel)
    with pytest.raises(cpl.CuratedClipError):
        cpl.produce_curated(
            {"video_url": "https://v.redd.it/x/DASH.mp4", "title": "t"}, channel,
            settings=SimpleNamespace(ffmpeg_path="ffmpeg", claude_cli_path="claude"),
            secrets={}, db_path=tmp_path / "db.sqlite", output_root=tmp_path,
            music_root=tmp_path, templates_dir=tmp_path)
