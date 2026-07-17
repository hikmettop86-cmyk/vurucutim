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
    assert not watermark_uncleanable(WatermarkDetect(present=False))
