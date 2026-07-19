"""SP4: kürate klip temizleme (hafif/kenar watermark → delogo)."""
import subprocess
from pathlib import Path

import pytest

from short_bot.curated_clean import WatermarkDetect, _REGION_BOX, clean_clip


def _make_clip(path: Path):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc=size=720x1280:rate=15:duration=2", "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=60)


def test_clean_clip_skips_when_absent():
    assert clean_clip("x.mp4", WatermarkDetect(present=False), out_path="o.mp4") is None


def test_clean_clip_skips_heavy_cover():
    # Yazı özneyi kaplıyorsa temizleme artefakt bırakır → dokunma.
    d = WatermarkDetect(present=True, regions=["top-right"], covers_subject=True)
    assert clean_clip("x.mp4", d, out_path="o.mp4") is None


def test_clean_clip_skips_unknown_region():
    d = WatermarkDetect(present=True, regions=["none"], covers_subject=False)
    assert clean_clip("x.mp4", d, out_path="o.mp4") is None


def test_region_boxes_cover_corners_and_edges():
    for r in ("top-left", "top-right", "bottom-left", "bottom-right", "top", "bottom"):
        assert r in _REGION_BOX


def test_clean_clip_delogo_runs(tmp_path):
    src = tmp_path / "src.mp4"
    _make_clip(src)
    out = tmp_path / "clean.mp4"
    d = WatermarkDetect(present=True, regions=["top-right"], covers_subject=False)
    res = clean_clip(src, d, out_path=out)
    assert res == out and out.exists()
    # geçerli, oynatılabilir video mü (delogo bozmadı)
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(out)],
                       capture_output=True, text=True, timeout=20)
    assert float((p.stdout or "0").strip()) > 1.0


def test_crop_source_banner_edges_only(tmp_path):
    """Kaynak yazı-bandı: ÜST/ALT kenara yapışık şerit kırpılır; ORTADA yüzen atlanır."""
    from short_bot.curated_clean import SourceBanner, crop_source_banner
    src = tmp_path / "src.mp4"
    _make_clip(src)
    # ÜST kenar (tepede) → kırpılır, süre korunur
    top = crop_source_banner(src, SourceBanner(present=True, y_center=0.05, frac=0.08),
                             out_path=tmp_path / "top.mp4")
    assert top is not None and top.exists()
    # ÜST BÖLGE ama tepede küçük boşluk (short 967: y≈0.12, top_edge≈0.09) → yine KIRPILIR
    # (bandın dibi üst %20 içinde; eskiden 'ortada yüzüyor' sanılıp kaçıyordu)
    top2 = crop_source_banner(src, SourceBanner(present=True, y_center=0.12, frac=0.06),
                              out_path=tmp_path / "top2.mp4")
    assert top2 is not None and top2.exists()
    # ALT kenar (dipte) → kırpılır
    bot = crop_source_banner(src, SourceBanner(present=True, y_center=0.95, frac=0.08),
                             out_path=tmp_path / "bot.mp4")
    assert bot is not None and bot.exists()
    # ORTADA yüzen bant → temiz kırpılamaz → None (dokunma, içerik koru)
    mid = crop_source_banner(src, SourceBanner(present=True, y_center=0.48, frac=0.08),
                             out_path=tmp_path / "mid.mp4")
    assert mid is None
    # yok / ihmal edilebilir ince → None
    assert crop_source_banner(src, SourceBanner(present=False),
                              out_path=tmp_path / "n.mp4") is None
    assert crop_source_banner(src, SourceBanner(present=True, y_center=0.02, frac=0.02),
                              out_path=tmp_path / "n2.mp4") is None
    # kırpılan üst şerit gerçekten daha kısa (yükseklik azaldı)
    def _h(p):
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=height", "-of", "csv=p=0", str(p)],
                           capture_output=True, text=True, timeout=20)
        return int((r.stdout or "0").strip())
    assert _h(top) < _h(src)


def test_watermark_uncleanable_moving_vs_static():
    from short_bot.curated_clean import watermark_uncleanable
    # tek SABİT köşe → temizlenebilir
    assert not watermark_uncleanable(WatermarkDetect(present=True, regions=["top-right"]))
    # HAREKETLİ (birden çok bölge, TikTok) → temizlenemez
    assert watermark_uncleanable(WatermarkDetect(present=True,
        regions=["bottom-left", "bottom-right", "center"]))
    # köşe-DIŞI kenar strip → temizlenemez
    assert watermark_uncleanable(WatermarkDetect(present=True, regions=["mid-left"]))
    # özneyi KAPLAYAN → temizlenemez
    assert watermark_uncleanable(WatermarkDetect(present=True, regions=["top-right"],
                                                 covers_subject=True))
    # TikTok PLATFORM logosu (moving=True): tek köşe raporlansa BİLE temizlenemez say
    # (short 937: vision 'bottom-right' dedi ama logo gezdiği için delogo ıskaladı)
    assert watermark_uncleanable(WatermarkDetect(present=True, regions=["bottom-right"],
                                                 moving=True))
    assert not watermark_uncleanable(WatermarkDetect(present=False))


def test_judge_clip_quality_gates_mundane(monkeypatch, tmp_path):
    """judge_clip_quality: storyboard vision → ClipQuality (engaging+score) döner; sıradan
    (düşük) klip ayırt edilebilsin. run_json/_storyboard_frames fonksiyon-içi import'lanır →
    KAYNAK modüllerinde patch'le."""
    import short_bot.claude_cli as cli
    import short_bot.reel as reel
    from short_bot.curated_clean import ClipQuality, judge_clip_quality

    monkeypatch.setattr(reel, "_storyboard_frames",
                        lambda clip, board, *a, **k: (Path(board).write_bytes(b"x") or True))
    monkeypatch.setattr(cli, "run_json",
                        lambda prompt, schema, **kw: ClipQuality(engaging=False, score=3))

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    q = judge_clip_quality(tmp_path / "clip.mp4", vision_call=_V(), tone="mizah")
    assert q is not None and q.engaging is False and q.score == 3


def test_verify_narration_faithfulness(monkeypatch, tmp_path):
    """verify_curated_narration: storyboard + anlatım → NarrationCheck; kaba uyumsuzlukta
    faithful=False. run_json/_storyboard_frames fonksiyon-içi import → kaynakta patch."""
    import short_bot.claude_cli as cli
    import short_bot.reel as reel
    from short_bot.curated_clean import NarrationCheck, verify_curated_narration

    monkeypatch.setattr(reel, "_storyboard_frames",
                        lambda clip, board, *a, **k: (Path(board).write_bytes(b"x") or True))
    monkeypatch.setattr(cli, "run_json",
                        lambda prompt, schema, **kw: NarrationCheck(faithful=False,
                                                                    mismatch="köpek yok"))

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    c = verify_curated_narration(tmp_path / "c.mp4", "bir köpek koşuyor", vision_call=_V())
    assert c is not None and c.faithful is False and c.mismatch == "köpek yok"
    # boş anlatım → None (yargılanmaz)
    assert verify_curated_narration(tmp_path / "c.mp4", "  ", vision_call=_V()) is None


def test_detect_heavy_text_flags_burned_captions(monkeypatch, tmp_path):
    """detect_heavy_text: storyboard → HeavyText; gömülü altyazı/banner DOLU (editlenmiş
    repost) klip yakalanır (short 968). run_json/_storyboard_frames kaynakta patch'lenir."""
    import short_bot.claude_cli as cli
    import short_bot.reel as reel
    from short_bot.curated_clean import HeavyText, detect_heavy_text

    monkeypatch.setattr(reel, "_storyboard_frames",
                        lambda clip, board, *a, **k: (Path(board).write_bytes(b"x") or True))
    monkeypatch.setattr(cli, "run_json",
                        lambda prompt, schema, **kw: HeavyText(heavy=True,
                                                               kinds=["subtitle", "banner"]))

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    r = detect_heavy_text(tmp_path / "c.mp4", vision_call=_V())
    assert r is not None and r.heavy is True and "subtitle" in r.kinds


def test_safety_schemas_reject_empty_json():
    """Güvenlik şemaları (WatermarkDetect/HeavyText/ClipQuality) BOŞ {} yanıtı REDDETMELİ →
    model_validate({}) ValidationError atsın ki run_json None dönsün → gate fail-closed/open
    DOĞRU çalışsın. Eskiden default'lar sessizce geçiyordu (kirli klip geçer / iyi klip elenir)."""
    import pytest
    from pydantic import ValidationError

    from short_bot.curated_clean import ClipQuality, HeavyText, WatermarkDetect

    for schema in (WatermarkDetect, HeavyText, ClipQuality):
        with pytest.raises(ValidationError):
            schema.model_validate({})
    # karar alanı VERİLİRSE geçerli (diğer alanlar default'lu kalır)
    assert WatermarkDetect.model_validate({"present": True}).present is True
    assert HeavyText.model_validate({"heavy": False}).heavy is False
    assert ClipQuality.model_validate({"engaging": True, "score": 8}).score == 8


def test_describe_clip_beats_time_ordered(monkeypatch, tmp_path):
    """describe_clip_beats: klibi segment'lere bölüp her dilimi AYRI tarif eder → zaman-sıralı
    beat sheet (BAŞ/ORTA/SON). Böylece anlatım footage SIRASINA oturur, ödül erken açılmaz
    (short 990: kullanıcı 'sahneler ile cümleler oturmuyor'). subprocess/storyboard/describe
    fonksiyon-içi import → kaynakta patch."""
    import subprocess
    import short_bot.footage_matcher as fm
    import short_bot.reel as reel
    from short_bot.curated_clean import describe_clip_beats

    # ffmpeg segment kesme → çıktı dosyasını yarat (başarı simüle); ffprobe çağrılmaz (duration_s verili)
    def _fake_run(cmd, *a, **k):
        try:
            Path(cmd[-1]).write_bytes(b"x")
        except Exception:  # noqa: BLE001
            pass
        class _R:
            returncode = 0; stdout = ""; stderr = ""
        return _R()
    monkeypatch.setattr(subprocess, "run", _fake_run)
    monkeypatch.setattr(reel, "_storyboard_frames",
                        lambda clip, board, *a, **k: (Path(board).write_bytes(b"x") or True))
    # her segment FARKLI (zaman-sıralı) tarif döndür
    _descs = iter(["a runner collapses, others pass",
                   "a yellow-shirt runner stops to help",
                   "several runners carry him to the finish"])
    monkeypatch.setattr(fm, "describe_storyboard", lambda board, **k: (next(_descs), False))

    class _V:
        claude_path = ""; model = ""; backend = "google_studio"; api_key = ""

    out = describe_clip_beats(tmp_path / "c.mp4", vision_call=_V(), duration_s=30, segments=3)
    # üç dilim de var, zaman-sıralı, her biri kendi tarifiyle
    assert "BAŞ" in out and "ORTA" in out and "SON" in out
    assert "collapses" in out and "yellow-shirt" in out and "carry him" in out
    assert out.index("BAŞ") < out.index("ORTA") < out.index("SON")
    # süre çok kısa / segment<2 → boş (fail-open, blok desc'e düşülür)
    assert describe_clip_beats(tmp_path / "c.mp4", vision_call=_V(), duration_s=3) == ""
