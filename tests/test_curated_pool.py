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


class _FakeNarration:
    """produce_curated'ın kullandığı ReelNarration arayüzünün minimal sahtesi."""
    hook = "Kanca cümlesi burada"
    title = "Test başlık"
    cover_title = "Kapak"
    title_en = ""

    def full_text(self):
        return "Kanca cümlesi burada. Olay şöyle oldu. Kapanış cümlesi."

    def word_count(self):
        return 8


def _mock_produce_chain(monkeypatch, tmp_path):
    """produce_curated'ı render DAHİL uçtan uca BAŞARIYLA geçirecek tam mock zinciri.
    Her kapı testi tek yargıcı bozarak kendi kapısını sınar."""
    from pathlib import Path
    from types import SimpleNamespace

    import short_bot.curated_clean as cc
    import short_bot.pipeline as pl
    import short_bot.reddit_gems as rg
    import short_bot.reel as reel_mod
    import short_bot.reel_narration as rn
    import short_bot.tts.ai33_client as ai33
    from short_bot.config import AICall
    from short_bot.curated_clean import (ClipQuality, HeavyText, NarrationCheck,
                                         WatermarkDetect)
    from short_bot.reel_narration import NarrationClarity, ToneFit

    fake = AICall(backend="google_studio", model="m", api_key=None, claude_path="")
    monkeypatch.setattr(pl, "resolve_ai_call", lambda *a, **k: fake)
    monkeypatch.setattr(ai33, "resolve_ai33_api_key", lambda *a, **k: "k")
    monkeypatch.setattr(rg, "download_clip",
                        lambda url, dest: (Path(dest).write_bytes(b"m"), Path(dest))[1])
    monkeypatch.setattr(cc, "clean_if_needed",
                        lambda clip, **k: (clip, WatermarkDetect(present=False)))
    monkeypatch.setattr(cc, "detect_source_banner", lambda clip, **k: None)
    monkeypatch.setattr(cc, "detect_heavy_text", lambda clip, **k: HeavyText(heavy=False))
    monkeypatch.setattr(reel_mod, "_clip_duration_s", lambda clip, *a, **k: 20.0)
    monkeypatch.setattr(reel_mod, "_describe_clip", lambda clip, **k: "kedi kutudan atliyor")
    monkeypatch.setattr(rn, "judge_tone_fit", lambda *a, **k: ToneFit(fits=True))
    monkeypatch.setattr(cc, "judge_clip_quality",
                        lambda clip, **k: ClipQuality(engaging=True, score=8))
    monkeypatch.setattr(cc, "describe_clip_beats", lambda clip, **k: "")
    monkeypatch.setattr(cc, "detect_scene_split", lambda clip, **k: None)
    monkeypatch.setattr(rn, "write_curated_narration", lambda *a, **k: _FakeNarration())
    monkeypatch.setattr(cc, "verify_curated_narration",
                        lambda clip, text, **k: NarrationCheck(faithful=True))
    monkeypatch.setattr(rn, "judge_narration_clarity",
                        lambda *a, **k: NarrationClarity(clear=True))

    def _fake_render(*a, out_path=None, **k):
        Path(out_path).write_bytes(b"rendered-video")

    monkeypatch.setattr(reel_mod, "produce_reel_video", _fake_render)
    # final QA (A): 'yargı yok' varsayılanı — fonksiyon henüz yokken de kurulabilsin (RED)
    monkeypatch.setattr(cc, "judge_final_video", lambda *a, **k: None, raising=False)

    reel = SimpleNamespace(enabled=True, curated_clean=True, persona="",
                           curated_tone="mizah", music_mood="upbeat",
                           target_duration_s=[25, 45])
    channel = SimpleNamespace(slug="kaosdayi", language="tr", reel=reel,
                              output_dir=str(tmp_path / "kaosdayi"))
    settings = SimpleNamespace(ffmpeg_path="ffmpeg", claude_cli_path="claude",
                               playwright_browser="chromium")
    return channel, settings


def test_produce_curated_passes_reveal_anchor_to_render(tmp_path, monkeypatch):
    """E) REVEAL ÇIPASI: klipteki dönüm anı (vision oranı) render'a GEÇMELİ — orada
    anlatımın ödül cümlesine çakıştırılıyor (short 1078: kucaklaşma 5sn önce görünüp
    reveal ıskalanmıştı)."""
    from pathlib import Path

    import short_bot.curated_clean as cc
    import short_bot.curated_pipeline as cpl
    import short_bot.reel as reel_mod

    channel, settings = _mock_produce_chain(monkeypatch, tmp_path)
    monkeypatch.setattr(cc, "detect_reveal_anchor", lambda clip, **k: 0.42, raising=False)
    seen = {}

    def _capture_render(*a, out_path=None, **k):
        seen.update(k)
        Path(out_path).write_bytes(b"rendered-video")

    monkeypatch.setattr(reel_mod, "produce_reel_video", _capture_render)

    cpl.produce_curated({"video_url": "https://v.redd.it/anc1/DASH.mp4", "title": "t"},
                        channel, settings=settings, secrets={}, db_path=tmp_path / "db.sqlite",
                        output_root=tmp_path, music_root=tmp_path, templates_dir=tmp_path)

    assert seen.get("curated_reveal_frac") == 0.42, f"çıpa render'a geçmedi: {sorted(seen)}"


def test_produce_curated_skips_when_clarity_fails_twice(tmp_path, monkeypatch):
    """B) NETLİK FAIL-CLOSED: netlik kapısı iki denemede de 'net değil' derse eskiden
    UYARIYLA YAYINLIYORDU (fail-open) — artık klip atlanır (çöp yayınlanmaz; sadakat
    kapısıyla aynı sözleşme). Klip seen'e YAZILMAZ (anlatım şanssızlığı, klip suçsuz)."""
    from types import SimpleNamespace as _SN  # noqa: F401

    import pytest

    import short_bot.curated_pipeline as cpl
    import short_bot.reel_narration as rn
    from short_bot.curated_pool import seen_keys
    from short_bot.db import init_db
    from short_bot.reel_narration import NarrationClarity

    channel, settings = _mock_produce_chain(monkeypatch, tmp_path)
    monkeypatch.setattr(rn, "judge_narration_clarity",
                        lambda *a, **k: NarrationClarity(clear=False, reason="kopuk hikâye"))
    db = tmp_path / "db.sqlite"
    with pytest.raises(cpl.CuratedClipError):
        cpl.produce_curated({"video_url": "https://v.redd.it/clr1/DASH.mp4", "title": "t"},
                            channel, settings=settings, secrets={}, db_path=db,
                            output_root=tmp_path, music_root=tmp_path,
                            templates_dir=tmp_path)
    assert seen_keys(init_db(db), "kaosdayi") == set()   # klip hatırlanmadı (haksız blacklist yok)


def test_produce_curated_rejects_audio_payload_clip(tmp_path, monkeypatch):
    """C) SES-YÜKÜ KAPISI: klibin etkisi SESTE ise (works_muted=False — kahkaha/diyalog)
    sessiz izlenince sıradanlaşır; biz orijinal sesi atıp TTS bastığımız için bu klip
    ÜRETİLMEMELİ ve kalıcı hatırlanmalı (klip özelliği, değişmez)."""
    import pytest

    import short_bot.curated_clean as cc
    import short_bot.curated_pipeline as cpl
    from short_bot.curated_clean import ClipQuality
    from short_bot.curated_pool import seen_keys
    from short_bot.db import init_db

    channel, settings = _mock_produce_chain(monkeypatch, tmp_path)
    monkeypatch.setattr(cc, "judge_clip_quality",
                        lambda clip, **k: ClipQuality(engaging=True, score=8,
                                                      works_muted=False))
    db = tmp_path / "db.sqlite"
    with pytest.raises(cpl.CuratedClipError):
        cpl.produce_curated({"video_url": "https://v.redd.it/aud1/DASH.mp4", "title": "t"},
                            channel, settings=settings, secrets={}, db_path=db,
                            output_root=tmp_path, music_root=tmp_path,
                            templates_dir=tmp_path)
    assert "vreddit:aud1" in seen_keys(init_db(db), "kaosdayi")   # kalıcı yargı


def test_produce_curated_final_qa_blocks_bad_video(tmp_path, monkeypatch):
    """A) FİNAL QA KAPISI: bitmiş (render edilmiş) video vision yargısında izlenmez/senkronsuz
    çıkarsa YAYINLANMAZ — dosya silinir, Short kaydı açılmaz, klip seen'e yazılmaz."""
    from types import SimpleNamespace

    import pytest

    import short_bot.curated_clean as cc
    import short_bot.curated_pipeline as cpl
    from short_bot.curated_pool import seen_keys
    from short_bot.db import init_db

    channel, settings = _mock_produce_chain(monkeypatch, tmp_path)
    bad = SimpleNamespace(watchable=False, sync_ok=True, tone_ok=True, score=3,
                          reason="anlatım görüntüyle alakasız")
    monkeypatch.setattr(cc, "judge_final_video", lambda *a, **k: bad, raising=False)
    db = tmp_path / "db.sqlite"
    with pytest.raises(cpl.CuratedClipError):
        cpl.produce_curated({"video_url": "https://v.redd.it/fqa1/DASH.mp4", "title": "t"},
                            channel, settings=settings, secrets={}, db_path=db,
                            output_root=tmp_path, music_root=tmp_path,
                            templates_dir=tmp_path)
    assert not list((tmp_path / "kaosdayi").glob("*.mp4"))        # çöp video silindi
    assert seen_keys(init_db(db), "kaosdayi") == set()            # klip hatırlanmadı


def test_produce_curated_final_qa_pass_and_fail_open(tmp_path, monkeypatch):
    """A) FİNAL QA: iyi yargı → üretim tamam; yargı None (vision hıçkırığı) → fail-open
    (önceki tüm kapılardan geçmiş render tek hıçkırıkla çöpe atılmaz)."""
    from types import SimpleNamespace

    import short_bot.curated_clean as cc
    import short_bot.curated_pipeline as cpl

    # iyi yargı → üretim tamamlanır
    channel, settings = _mock_produce_chain(monkeypatch, tmp_path)
    good = SimpleNamespace(watchable=True, sync_ok=True, tone_ok=True, score=8, reason="")
    monkeypatch.setattr(cc, "judge_final_video", lambda *a, **k: good, raising=False)
    sid, out = cpl.produce_curated(
        {"video_url": "https://v.redd.it/ok1/DASH.mp4", "title": "t"}, channel,
        settings=settings, secrets={}, db_path=tmp_path / "db.sqlite",
        output_root=tmp_path, music_root=tmp_path, templates_dir=tmp_path)
    assert sid and out.exists()

    # None yargı → fail-open, üretim yine tamamlanır
    monkeypatch.setattr(cc, "judge_final_video", lambda *a, **k: None, raising=False)
    sid2, out2 = cpl.produce_curated(
        {"video_url": "https://v.redd.it/ok2/DASH.mp4", "title": "t2"}, channel,
        settings=settings, secrets={}, db_path=tmp_path / "db.sqlite",
        output_root=tmp_path, music_root=tmp_path, templates_dir=tmp_path)
    assert sid2 and out2.exists()


class _RecLog:
    """Koşu logger'ının sahtesi — hangi seviyede ne yazıldığını tutar."""

    def __init__(self):
        self.records: list[tuple[str, str]] = []

    def info(self, msg, *a, **k):
        self.records.append(("info", str(msg)))

    def warning(self, msg, *a, **k):
        self.records.append(("warning", str(msg)))

    def error(self, msg, *a, **k):
        self.records.append(("error", str(msg)))

    def debug(self, msg, *a, **k):
        self.records.append(("debug", str(msg)))


def test_final_qa_failure_is_visible_in_run_log(tmp_path, monkeypatch):
    """B) YARGILANMAYAN VİDEO SESSİZCE GEÇMEZ.

    GERÇEK HATA (short 1077): yargıç None döndü, kapı fail-open geçti ve koşu logunda
    TEK SATIR bile yoktu — operatör 'final QA'dan geçti' sanıyordu. curated_clean'in
    kendi logger'ı koşu dosyasına bağlı değil; uyarı KOŞU logger'ına yazılmalı."""
    from types import SimpleNamespace   # noqa: F401 — mock zinciri kullanıyor

    import short_bot.curated_clean as cc
    import short_bot.curated_pipeline as cpl

    channel, settings = _mock_produce_chain(monkeypatch, tmp_path)
    monkeypatch.setattr(cc, "judge_final_video", lambda *a, **k: None, raising=False)
    rec = _RecLog()

    sid, out = cpl.produce_curated(
        {"video_url": "https://v.redd.it/qa0/DASH.mp4", "title": "t"}, channel,
        settings=settings, secrets={}, db_path=tmp_path / "db.sqlite",
        output_root=tmp_path, music_root=tmp_path, templates_dir=tmp_path, log=rec)

    assert sid and out.exists(), "fail-open korunmalı (render çöpe atılmaz)"
    warns = [m for lvl, m in rec.records if lvl == "warning" and "final" in m.lower()]
    assert warns, f"yargılanamayan video sessizce geçti: {rec.records}"


def test_produce_curated_remembers_dead_clip_403(tmp_path, monkeypatch):
    """ÖLÜ-KLİP HAFIZASI: v.redd.it 403/404 (post silinmiş) KALICIDIR — klip 'gone' olarak
    hatırlanmalı ki her koşuda yeniden en-iyi-aday seçilip yeniden 403 almasın (otter döngüsü:
    tek güçlü aday hep aynı ölü klip → her koşu 'temiz cevher yok')."""
    from types import SimpleNamespace

    import pytest
    import requests

    import short_bot.curated_pipeline as cpl
    import short_bot.pipeline as pl
    import short_bot.reddit_gems as rg
    import short_bot.tts.ai33_client as ai33
    from short_bot.config import AICall
    from short_bot.curated_pool import seen_keys
    from short_bot.db import init_db

    fake = AICall(backend="google_studio", model="m", api_key=None, claude_path="")
    monkeypatch.setattr(pl, "resolve_ai_call", lambda *a, **k: fake)
    monkeypatch.setattr(ai33, "resolve_ai33_api_key", lambda *a, **k: "k")
    resp = requests.Response()
    resp.status_code = 403
    err = requests.HTTPError("403 Client Error: Forbidden", response=resp)
    monkeypatch.setattr(rg, "download_clip",
                        lambda url, dest: (_ for _ in ()).throw(err))

    reel = SimpleNamespace(enabled=True, curated_clean=True, persona="", curated_tone="mizah")
    channel = SimpleNamespace(slug="kaosdayi", language="tr", reel=reel)
    db = tmp_path / "db.sqlite"
    with pytest.raises(cpl.CuratedClipError):
        cpl.produce_curated(
            {"video_url": "https://v.redd.it/dead1/DASH_480.mp4", "title": "t"}, channel,
            settings=SimpleNamespace(ffmpeg_path="ffmpeg", claude_cli_path="claude"),
            secrets={}, db_path=db, output_root=tmp_path,
            music_root=tmp_path, templates_dir=tmp_path)
    assert seen_keys(init_db(db), "kaosdayi") == {"vreddit:dead1"}


def test_produce_curated_forgets_transient_download_error(tmp_path, monkeypatch):
    """GEÇİCİ indirme hatası (timeout/ağ — HTTP durum kodu YOK) hatırlanMAZ → sonraki
    koşuda tekrar denensin (mevcut sözleşme korunur)."""
    from types import SimpleNamespace

    import pytest
    import requests

    import short_bot.curated_pipeline as cpl
    import short_bot.pipeline as pl
    import short_bot.reddit_gems as rg
    import short_bot.tts.ai33_client as ai33
    from short_bot.config import AICall
    from short_bot.curated_pool import seen_keys
    from short_bot.db import init_db

    fake = AICall(backend="google_studio", model="m", api_key=None, claude_path="")
    monkeypatch.setattr(pl, "resolve_ai_call", lambda *a, **k: fake)
    monkeypatch.setattr(ai33, "resolve_ai33_api_key", lambda *a, **k: "k")
    err = requests.ConnectionError("bağlantı koptu")
    monkeypatch.setattr(rg, "download_clip",
                        lambda url, dest: (_ for _ in ()).throw(err))

    reel = SimpleNamespace(enabled=True, curated_clean=True, persona="", curated_tone="mizah")
    channel = SimpleNamespace(slug="kaosdayi", language="tr", reel=reel)
    db = tmp_path / "db.sqlite"
    with pytest.raises(cpl.CuratedClipError):
        cpl.produce_curated(
            {"video_url": "https://v.redd.it/temp1/DASH_480.mp4", "title": "t"}, channel,
            settings=SimpleNamespace(ffmpeg_path="ffmpeg", claude_cli_path="claude"),
            secrets={}, db_path=db, output_root=tmp_path,
            music_root=tmp_path, templates_dir=tmp_path)
    assert seen_keys(init_db(db), "kaosdayi") == set()


def test_auto_produce_remembers_score_stage_rejects(tmp_path, monkeypatch):
    """SKOR-AŞAMASI HAFIZASI (kullanıcı: 'milyonlarca video var, bulamıyor'): yazılı-kapak
    (has_text) ve eşik-altı skor KALICI yargıdır → koşu boş dönse bile seen'e yazılmalı.
    Yoksa top-60 penceresi her koşu AYNI klipleri yeniden skorlar, taze adaylar pencereye
    hiç giremez. Geçici skor hatası (score_err) ise hatırlanMAZ."""
    from types import SimpleNamespace

    import short_bot.claude_cli as cc
    import short_bot.curated_pipeline as cpl
    import short_bot.pipeline as pl
    import short_bot.reddit_gems as rg
    from short_bot.config import AICall
    from short_bot.curated_pool import seen_keys
    from short_bot.curated_rank import CuriosityScore
    from short_bot.db import init_db

    gems = [
        {"video_url": "https://v.redd.it/kirli1/DASH.mp4", "title": "KIRLI yazili kapak",
         "permalink": "https://reddit.com/r/aww/1", "sub": "aww", "ups": 9000,
         "comments": 30, "duration": 60, "orient": "DİKEY", "thumb": ""},
        {"video_url": "https://v.redd.it/zayif1/DASH.mp4", "title": "ZAYIF sıradan an",
         "permalink": "https://reddit.com/r/aww/2", "sub": "aww", "ups": 8000,
         "comments": 30, "duration": 60, "orient": "DİKEY", "thumb": ""},
        {"video_url": "https://v.redd.it/hata1/DASH.mp4", "title": "HATA veren skor",
         "permalink": "https://reddit.com/r/aww/3", "sub": "aww", "ups": 7000,
         "comments": 30, "duration": 60, "orient": "DİKEY", "thumb": ""},
    ]
    monkeypatch.setattr(rg, "find_gems", lambda *a, **k: gems)
    fake = AICall(backend="google_studio", model="m", api_key=None, claude_path="")
    monkeypatch.setattr(pl, "resolve_ai_call", lambda *a, **k: fake)

    def _fake_run_json(prompt, schema, **kw):
        if "HATA" in prompt:
            raise RuntimeError("geçici vision hatası")
        if "KIRLI" in prompt:
            return CuriosityScore(score=8, has_text=True)
        return CuriosityScore(score=4, has_text=False)   # ZAYIF: eşik (7) altı

    monkeypatch.setattr(cc, "run_json", _fake_run_json)

    reel = SimpleNamespace(curated_tone="duygu", subreddits=[], curated_time="month",
                           curated_min_ups=500, curated_max_duration=90)
    channel = SimpleNamespace(slug="dayidiyorki", reel=reel)
    db = tmp_path / "db.sqlite"
    sid, path = cpl.auto_produce_curated(
        channel, settings=SimpleNamespace(ffmpeg_path="ffmpeg", claude_cli_path="claude"),
        secrets={"reddit_client_id": "x", "reddit_client_secret": "y"},
        db_path=db, output_root=tmp_path, music_root=tmp_path, templates_dir=tmp_path)
    assert sid is None   # güçlü aday yok → üretim yok (boş koşu)
    # AMA elenenler HATIRLANDI: yazılı → heavy-text, eşik-altı → weak-score;
    # geçici skor hatası (HATA) hatırlanMADI (tekrar denenebilir).
    assert seen_keys(init_db(db), "dayidiyorki") == {"vreddit:kirli1", "vreddit:zayif1"}


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


# --------------------------------------------------------- DİL KAPISI (Japonca kanal)
#
# Operatör Japonca bilmiyor: Türkçe kanalda "bu anlatım anlamsız" diyebildiği geri
# bildirim döngüsü yabancı dilde KOPUYOR. Sadakat kapısı GÖRÜNTÜYE, netlik kapısı
# MANTIĞA bakar — ikisi de metnin o dilde DOĞAL olup olmadığını sormaz.

def _ja_channel(channel):
    """Aynı mock zinciri, kanal dili Japonca."""
    channel.language = "ja"
    return channel


def test_language_gate_skipped_for_turkish_channel(tmp_path, monkeypatch):
    """Türkçe kanalda yerli-okur ÇAĞRILMAZ — gereksiz LLM çağrısı = boşa para."""
    import short_bot.curated_pipeline as cpl
    import short_bot.lang_review as lr

    called = {"n": 0}

    def _judge(*a, **k):
        called["n"] += 1
        return lr.NativeVerdict(natural=True)

    channel, settings = _mock_produce_chain(monkeypatch, tmp_path)
    monkeypatch.setattr(lr, "judge_native_text", _judge)
    monkeypatch.setattr(lr, "back_translate", lambda *a, **k: "")

    cpl.produce_curated({"video_url": "https://v.redd.it/tr1/DASH.mp4", "title": "t"},
                        channel, settings=settings, secrets={}, db_path=tmp_path / "db.sqlite",
                        output_root=tmp_path, music_root=tmp_path, templates_dir=tmp_path)
    assert called["n"] == 0


def test_language_gate_runs_for_foreign_channel(tmp_path, monkeypatch):
    import short_bot.curated_pipeline as cpl
    import short_bot.lang_review as lr

    seen = {}

    def _judge(text, *, language, **k):
        seen["language"] = language
        return lr.NativeVerdict(natural=True)

    channel, settings = _mock_produce_chain(monkeypatch, tmp_path)
    _ja_channel(channel)
    monkeypatch.setattr(lr, "judge_native_text", _judge)
    monkeypatch.setattr(lr, "back_translate", lambda *a, **k: "")

    cpl.produce_curated({"video_url": "https://v.redd.it/ja1/DASH.mp4", "title": "t"},
                        channel, settings=settings, secrets={}, db_path=tmp_path / "db.sqlite",
                        output_root=tmp_path, music_root=tmp_path, templates_dir=tmp_path)
    assert seen.get("language") == "ja"


def test_language_gate_rewrites_once_then_passes(tmp_path, monkeypatch):
    """Doğal değilse GERİ BİLDİRİMLE yeniden yazdır (sadakat/netlik kapılarıyla aynı sözleşme)."""
    import short_bot.curated_pipeline as cpl
    import short_bot.lang_review as lr
    import short_bot.reel_narration as rn

    verdicts = iter([lr.NativeVerdict(natural=False, issue="çeviri kokuyor: '〜であります'"),
                     lr.NativeVerdict(natural=True)])
    rewrites = []

    channel, settings = _mock_produce_chain(monkeypatch, tmp_path)
    _ja_channel(channel)
    monkeypatch.setattr(lr, "judge_native_text", lambda *a, **k: next(verdicts))
    monkeypatch.setattr(lr, "back_translate", lambda *a, **k: "")

    def _write(*a, **k):
        rewrites.append(k.get("feedback") or "")
        return _FakeNarration()

    monkeypatch.setattr(rn, "write_curated_narration", _write)

    cpl.produce_curated({"video_url": "https://v.redd.it/ja2/DASH.mp4", "title": "t"},
                        channel, settings=settings, secrets={}, db_path=tmp_path / "db.sqlite",
                        output_root=tmp_path, music_root=tmp_path, templates_dir=tmp_path)
    assert any("çeviri kokuyor" in f for f in rewrites), rewrites


def test_language_gate_fails_closed_after_second_failure(tmp_path, monkeypatch):
    """İki denemede de doğal değilse ÇÖP YAYINLAMA — operatör bunu göremez, yakalayan yok."""
    import pytest

    import short_bot.curated_pipeline as cpl
    import short_bot.lang_review as lr

    channel, settings = _mock_produce_chain(monkeypatch, tmp_path)
    _ja_channel(channel)
    monkeypatch.setattr(lr, "judge_native_text",
                        lambda *a, **k: lr.NativeVerdict(natural=False, issue="bozuk"))
    monkeypatch.setattr(lr, "back_translate", lambda *a, **k: "")

    with pytest.raises(cpl.CuratedClipError):
        cpl.produce_curated({"video_url": "https://v.redd.it/ja3/DASH.mp4", "title": "t"},
                            channel, settings=settings, secrets={},
                            db_path=tmp_path / "db.sqlite", output_root=tmp_path,
                            music_root=tmp_path, templates_dir=tmp_path)


def test_back_translation_is_stored_for_the_operator(tmp_path, monkeypatch):
    """Geri çeviri script_json'a YAZILMALI — panelde Japoncanın yanında görünecek."""
    import json

    import short_bot.curated_pipeline as cpl
    import short_bot.lang_review as lr
    from short_bot.db import init_db, shorts

    channel, settings = _mock_produce_chain(monkeypatch, tmp_path)
    _ja_channel(channel)
    monkeypatch.setattr(lr, "judge_native_text",
                        lambda *a, **k: lr.NativeVerdict(natural=True))
    monkeypatch.setattr(lr, "back_translate",
                        lambda *a, **k: "Bu çocuk hastanede yalnızdı.")

    db_path = tmp_path / "db.sqlite"
    short_id, _ = cpl.produce_curated(
        {"video_url": "https://v.redd.it/ja4/DASH.mp4", "title": "t"}, channel,
        settings=settings, secrets={}, db_path=db_path, output_root=tmp_path,
        music_root=tmp_path, templates_dir=tmp_path)

    eng = init_db(db_path)
    with eng.connect() as c:
        from sqlalchemy import select
        row = c.execute(select(shorts.c.script_json)
                        .where(shorts.c.id == short_id)).fetchone()
    d = json.loads(row.script_json)
    assert d.get("body_paragraph_tr") == "Bu çocuk hastanede yalnızdı."


def test_language_rewrite_is_a_repair_not_a_fresh_draft(tmp_path, monkeypatch):
    """ONARIM sözleşmesi: geri bildirim ÖNCEKİ METNİ içermeli ve 'sadece işaretleneni
    değiştir' demeli.

    ÖLÇÜLDÜ (2026-07-24, iki klip): her yeniden yazım sıfırdan yeni bir taslak üretip
    YENİ bir dil kusuru getiriyordu (1. deneme nezaket karışıklığı → 2. deneme farklı
    bir çeviri kokusu) — yakınsamıyor, klip boşuna kaybediliyor."""
    import short_bot.curated_pipeline as cpl
    import short_bot.lang_review as lr
    import short_bot.reel_narration as rn

    verdicts = iter([lr.NativeVerdict(natural=False, issue="'荒い息を繰り返す' fazlalık"),
                     lr.NativeVerdict(natural=True)])
    seen = {}

    channel, settings = _mock_produce_chain(monkeypatch, tmp_path)
    channel.language = "ja"
    monkeypatch.setattr(lr, "judge_native_text", lambda *a, **k: next(verdicts))
    monkeypatch.setattr(lr, "back_translate", lambda *a, **k: "")

    def _write(*a, **k):
        seen["feedback"] = k.get("feedback") or ""
        return _FakeNarration()

    monkeypatch.setattr(rn, "write_curated_narration", _write)

    cpl.produce_curated({"video_url": "https://v.redd.it/rep1/DASH.mp4", "title": "t"},
                        channel, settings=settings, secrets={}, db_path=tmp_path / "db.sqlite",
                        output_root=tmp_path, music_root=tmp_path, templates_dir=tmp_path)

    fb = seen.get("feedback", "")
    assert "荒い息を繰り返す" in fb, "işaretlenen ifade geri bildirime girmemiş"
    assert _FakeNarration().full_text() in fb, "önceki metin geri bildirime girmemiş"
    assert "ONARIM" in fb or "onar" in fb.lower(), fb[:200]


def test_language_gate_survives_two_sequential_issues(tmp_path, monkeypatch):
    """Yargıç her çağrıda YALNIZ EN KÖTÜ kusuru bildiriyor → iki kusurlu metin tek
    onarımla temizlenemez. ÖLÇÜLDÜ (aday 71): 1. onarım fiili düzeltti, hemen ardından
    CTA kalıbı işaretlendi ve İYİ bir klip kaybedildi. Kapı gevşemiyor — sadece
    onarım turu 2."""
    import short_bot.curated_pipeline as cpl
    import short_bot.lang_review as lr
    import short_bot.reel_narration as rn

    verdicts = iter([lr.NativeVerdict(natural=False, issue="'支え続ける' tuhaf"),
                     lr.NativeVerdict(natural=False, issue="'ハートを残して' çeviri kokuyor"),
                     lr.NativeVerdict(natural=True)])
    repairs = []

    channel, settings = _mock_produce_chain(monkeypatch, tmp_path)
    channel.language = "ja"
    monkeypatch.setattr(lr, "judge_native_text", lambda *a, **k: next(verdicts))
    monkeypatch.setattr(lr, "back_translate", lambda *a, **k: "")

    def _write(*a, **k):
        repairs.append(k.get("feedback") or "")
        return _FakeNarration()

    monkeypatch.setattr(rn, "write_curated_narration", _write)

    short_id, _ = cpl.produce_curated(
        {"video_url": "https://v.redd.it/two1/DASH.mp4", "title": "t"}, channel,
        settings=settings, secrets={}, db_path=tmp_path / "db.sqlite",
        output_root=tmp_path, music_root=tmp_path, templates_dir=tmp_path)

    assert short_id is not None
    # repairs[0] = ilk yazım (feedback yok); onarımlar ondan sonrakiler
    fixes = [f for f in repairs if "ONARIM" in f]
    assert len(fixes) == 2, repairs
    assert "ハートを残して" in fixes[1], "ikinci onarım ikinci kusuru almamış"


def test_language_gate_still_fails_closed_after_the_repair_budget(tmp_path, monkeypatch):
    """Bütçe bitince YİNE atlanıyor — 'sert kalsın' kararı korunuyor."""
    import pytest

    import short_bot.curated_pipeline as cpl
    import short_bot.lang_review as lr

    channel, settings = _mock_produce_chain(monkeypatch, tmp_path)
    channel.language = "ja"
    monkeypatch.setattr(lr, "judge_native_text",
                        lambda *a, **k: lr.NativeVerdict(natural=False, issue="hep bozuk"))
    monkeypatch.setattr(lr, "back_translate", lambda *a, **k: "")

    with pytest.raises(cpl.CuratedClipError):
        cpl.produce_curated({"video_url": "https://v.redd.it/two2/DASH.mp4", "title": "t"},
                            channel, settings=settings, secrets={},
                            db_path=tmp_path / "db.sqlite", output_root=tmp_path,
                            music_root=tmp_path, templates_dir=tmp_path)


def test_produce_curated_records_published_video_duration(tmp_path, monkeypatch):
    """DB'ye KAYNAK klibin süresi değil, YAYINLANAN videonun süresi yazılmalı.

    GERÇEK HATA (short 1140/1145): panel 55sn gösteriyordu ama videolar 41.3 / 37.4sn'ydi.
    Kürate klibi videoya setpts ile oturtuluyor (hızlandırma/yavaşlatma) → kaynak süre
    yayınlanan süreyi ARTIK temsil etmiyor."""
    import sqlite3

    import short_bot.curated_pipeline as cpl
    import short_bot.reel as reel_mod

    channel, settings = _mock_produce_chain(monkeypatch, tmp_path)

    # kaynak klip 20s; render edilen video (kanal çıktı klasöründe) 14s
    def _dur(clip, *a, **k):
        return 14.0 if "kaosdayi" in str(clip) else 20.0

    monkeypatch.setattr(reel_mod, "_clip_duration_s", _dur)

    db = tmp_path / "db.sqlite"
    sid, out = cpl.produce_curated(
        {"video_url": "https://v.redd.it/dur1/DASH.mp4", "title": "t"},
        channel, settings=settings, secrets={}, db_path=db,
        output_root=tmp_path, music_root=tmp_path, templates_dir=tmp_path)

    con = sqlite3.connect(db)
    got = con.execute("select duration_s from shorts where id=?", (sid,)).fetchone()[0]
    con.close()
    assert got == 14, f"DB'ye yayınlanan videonun süresi değil {got}sn yazıldı"


def test_collect_pool_prechecks_heavy_text_and_watermark(tmp_path, monkeypatch):
    """HAVUZA ÖN-DENETİM: gömülü yazı / temizlenemez watermark havuza GİRMESİN.

    ÖLÇÜM (dayidiyorki, 535 görülmüş klip): elemelerin %48'i heavy-text, %2'si
    watermark. Bu iki kapı ancak operatör 'üret' dedikten SONRA, klip indirilince
    çalışıyordu → panelde 'hazır' görünen cevherler üretimde eleniyordu (7/7).
    Oysa collect_pool klibi ZATEN indirip kalite yargısı yapıyor; aynı klip elde
    iken bu iki kontrolü de yapmamak için sebep yok — maliyet yalnız vision çağrısı.

    Elenen klip seen_clips'e KALICI yazılır (bir daha indirilmesin): ikisi de klibin
    değişmez özelliği.
    """
    from pathlib import Path
    from types import SimpleNamespace

    import short_bot.curated_clean as cc
    import short_bot.curated_pool as cp
    import short_bot.curated_rank as cr
    import short_bot.pipeline as pl
    import short_bot.reddit_gems as rg
    from short_bot.curated_clean import ClipQuality, HeavyText, WatermarkDetect
    from short_bot.db import init_db

    gems = [
        {"video_url": f"https://v.redd.it/p{i}/DASH.mp4", "title": f"klip{i}",
         "permalink": f"https://reddit.com/r/aww/{i}", "sub": "aww",
         "ups": 5000 - i * 100, "comments": 20, "duration": 30, "width": 1080,
         "height": 1920, "orient": "DİKEY", "thumb": ""}
        for i in range(3)
    ]
    monkeypatch.setattr(rg, "find_gems", lambda *a, **k: gems)
    monkeypatch.setattr(rg, "fetch_popular", lambda *a, **k: [])
    monkeypatch.setattr(rg, "download_clip",
                        lambda url, dest: (Path(dest).write_bytes(b"m"), Path(dest))[1])
    fake = SimpleNamespace(backend="google_studio", model="m", api_key=None, claude_path="")
    monkeypatch.setattr(pl, "resolve_ai_call", lambda *a, **k: fake)
    monkeypatch.setattr(cr, "score_curiosity",
                        lambda gems_, **k: [dict(g, curiosity=9) for g in gems_])
    monkeypatch.setattr(cc, "judge_clip_quality",
                        lambda clip, **k: ClipQuality(engaging=True, score=9))
    monkeypatch.setattr(cc, "detect_source_banner", lambda clip, **k: None)
    monkeypatch.setattr(cc, "crop_source_banner", lambda clip, b, **k: None)

    # p0 → temizlenemez watermark, p1 → gömülü altyazı, p2 → temiz
    def _clean(clip, **k):
        if "q0" in str(clip):
            return clip, WatermarkDetect(present=True, regions=["moving"],
                                         covers_subject=True)
        return clip, WatermarkDetect(present=False)

    def _heavy(clip, **k):
        return HeavyText(heavy="q1" in str(clip), kinds=["subtitle"])

    monkeypatch.setattr(cc, "clean_if_needed", _clean)
    monkeypatch.setattr(cc, "detect_heavy_text", _heavy)

    reel = SimpleNamespace(enabled=True, curated_tone="duygu", curated_min_ups=500,
                           curated_max_duration=90, subreddits=[], curated_time="month",
                           curated_include_popular=False)
    channel = SimpleNamespace(slug="dayidiyorki", content_source="curated", reel=reel)
    db = tmp_path / "pool.db"
    added = cp.collect_pool(channel, settings=SimpleNamespace(ffmpeg_path="ffmpeg"),
                            secrets={"reddit_client_id": "x", "reddit_client_secret": "y"},
                            db_path=db)

    assert added == 1, f"kirli klipler havuza girdi (eklenen={added})"
    eng = init_db(db)
    rows = cp.list_pool(eng, "dayidiyorki")
    assert [r["title"] for r in rows] == ["klip2"], f"havuzda yanlış cevher: {rows}"
    # ikisi de KALICI hatırlanmalı — bir daha indirilip yargılanmasın
    assert cp.seen_keys(eng, "dayidiyorki") == {cp.clip_key(gems[0]["video_url"]),
                                               cp.clip_key(gems[1]["video_url"])}


def test_clean_pool_prechecks_existing_gems(tmp_path, monkeypatch):
    """RETRO DENETİM: havuzda ZATEN duran cevherler de ön-denetimden geçmeli.

    collect_pool'a ön-denetim eklemek yalnız YENİ cevherleri korur; operatörün panelde
    gördüğü mevcut havuz (dayidiyorki'de 37 cevher) denetimsiz kalır ve üretimde
    elenmeye devam eder — kullanıcının asıl şikâyeti buydu. clean_pool zaten her
    cevheri İNDİRİP kalite yargılıyor; aynı klip elde iken watermark + gömülü yazı
    kontrolü de yapılmalı."""
    from pathlib import Path
    from types import SimpleNamespace

    import short_bot.curated_clean as cc
    import short_bot.curated_pool as cp
    import short_bot.curated_rank as cr
    import short_bot.pipeline as pl
    import short_bot.reddit_gems as rg
    from short_bot.curated_clean import ClipQuality, HeavyText, WatermarkDetect
    from short_bot.db import init_db, pooled_gems

    db = tmp_path / "clean.db"
    eng = init_db(db)
    with eng.begin() as c:
        for i in range(3):
            c.execute(pooled_gems.insert().values(
                channel="dayidiyorki", clip_key=f"vreddit:c{i}",
                video_url=f"https://v.redd.it/c{i}/DASH.mp4", permalink=f"p{i}",
                title=f"eski{i}", sub="aww", ups=1000, comments=5, duration=30,
                width=1080, height=1920, orient="DİKEY", thumb="", score=9.0,
                tone="duygu", status="pending"))

    fake = SimpleNamespace(backend="google_studio", model="m", api_key=None, claude_path="")
    monkeypatch.setattr(pl, "resolve_ai_call", lambda *a, **k: fake)
    monkeypatch.setattr(cr, "score_curiosity", lambda gems_, **k: gems_)   # thumbnail temiz
    monkeypatch.setattr(rg, "download_clip",
                        lambda url, dest: (Path(dest).write_bytes(b"m"), Path(dest))[1])
    monkeypatch.setattr(cc, "judge_clip_quality",
                        lambda clip, **k: ClipQuality(engaging=True, score=9))
    monkeypatch.setattr(cc, "detect_source_banner", lambda clip, **k: None)
    monkeypatch.setattr(cc, "crop_source_banner", lambda clip, b, **k: None)
    monkeypatch.setattr(cc, "clean_if_needed", lambda clip, **k: (
        (clip, WatermarkDetect(present=True, regions=["moving"], covers_subject=True))
        if "c0" in str(clip) else (clip, WatermarkDetect(present=False))))
    monkeypatch.setattr(cc, "detect_heavy_text",
                        lambda clip, **k: HeavyText(heavy="c1" in str(clip),
                                                    kinds=["subtitle"]))

    reel = SimpleNamespace(enabled=True, curated_tone="duygu")
    channel = SimpleNamespace(slug="dayidiyorki", content_source="curated", reel=reel)
    n = cp.clean_pool([channel], settings=SimpleNamespace(ffmpeg_path="ffmpeg"),
                      secrets={}, db_path=db)

    assert n == 2, f"kirli cevherler havuzda kaldı (elenen={n})"
    kalan = [r["title"] for r in cp.list_pool(eng, "dayidiyorki")]
    assert kalan == ["eski2"], f"havuzda yanlış cevher kaldı: {kalan}"
