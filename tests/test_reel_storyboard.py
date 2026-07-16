"""Storyboard vision: klip başına TEK kare yerine zaman-sıralı N kare (kullanıcı önerisi
2026-07-16). Vision klibin BOYUNCA ne olduğunu (aksiyon) görür → senaryo gerçek footage'a
yazılır, tek donmuş andan tahmin yürütmez. Storyboard kurulamazsa tek-kareye düşülür."""
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


def _sentetik(tmp_path, adi, sn):
    """Basit hareketli testsrc klibi."""
    p = tmp_path / adi
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"testsrc=duration={sn}:size=192x108:rate=8", str(p)],
        check=True, capture_output=True, timeout=60)
    return p


def test_clip_duration_okur(tmp_path):
    from short_bot.reel import _clip_duration_s
    klip = _sentetik(tmp_path, "d.mp4", 5)
    assert abs(_clip_duration_s(klip, "ffmpeg") - 5.0) < 0.6


def test_clip_duration_bozuk_sifir(tmp_path):
    from short_bot.reel import _clip_duration_s
    bozuk = tmp_path / "b.mp4"
    bozuk.write_bytes(b"mp4")
    assert _clip_duration_s(bozuk, "ffmpeg") == 0.0


def test_storyboard_frames_izgara_uretir(tmp_path):
    from short_bot.reel import _storyboard_frames
    klip = _sentetik(tmp_path, "sb.mp4", 6)
    board = tmp_path / "board.jpg"
    ok = _storyboard_frames(klip, board, "ffmpeg", cols=3, rows=2)
    assert ok is True
    assert board.exists() and board.stat().st_size > 0
    from PIL import Image
    w, h = Image.open(board).size
    assert w > h            # 3×2 ızgara → yatay geniş (tek kare 16:9 değil)


def test_storyboard_frames_bozuk_klip_false(tmp_path):
    from short_bot.reel import _storyboard_frames
    bozuk = tmp_path / "b.mp4"
    bozuk.write_bytes(b"mp4")
    board = tmp_path / "board.jpg"
    assert _storyboard_frames(bozuk, board, "ffmpeg") is False   # süre 0 → storyboard yok


def test_describe_storyboard_aksiyon_ve_static_parse(tmp_path, monkeypatch):
    import short_bot.claude_cli as CC
    from short_bot.footage_matcher import describe_storyboard
    from PIL import Image
    board = tmp_path / "b.jpg"
    Image.new("RGB", (300, 200)).save(board, "JPEG")
    yakalanan = {}

    def fake_rj(prompt, schema, **kw):
        yakalanan["p"] = prompt
        return schema(content="an alligator slowly opens its jaws then lunges",
                      is_static=False)

    monkeypatch.setattr(CC, "run_json", fake_rj)
    vc = SimpleNamespace(claude_path="c", model="m", backend="b", api_key=None)
    content, static = describe_storyboard(board, vision_call=vc, n_frames=6)
    assert content == "an alligator slowly opens its jaws then lunges"
    assert static is False
    assert "STORYBOARD" in yakalanan["p"] and "6" in yakalanan["p"]   # zaman-sıralı, n=6


def test_describe_storyboard_cokerse_bos(tmp_path, monkeypatch):
    import short_bot.claude_cli as CC
    from short_bot.footage_matcher import describe_storyboard
    from PIL import Image
    board = tmp_path / "b.jpg"
    Image.new("RGB", (300, 200)).save(board, "JPEG")

    def patlar(prompt, schema, **kw):
        raise RuntimeError("vision down")

    monkeypatch.setattr(CC, "run_json", patlar)
    vc = SimpleNamespace(claude_path="c", model="m", backend="b", api_key=None)
    content, static = describe_storyboard(board, vision_call=vc)
    assert content == "" and static is False        # fail-open


def test_describe_clip_storyboard_kullanir(tmp_path, monkeypatch):
    # storyboard başarılı → aksiyon tarifi döner, tek-kare yolu ÇAĞRILMAZ.
    import short_bot.reel as R
    import short_bot.footage_matcher as FM

    monkeypatch.setattr(R, "_storyboard_frames",
                        lambda c, o, f, **k: (Path(o).write_bytes(b"x"), True)[1])
    monkeypatch.setattr(FM, "describe_storyboard",
                        lambda p, **k: ("an alligator lunges forward", False))
    monkeypatch.setattr(FM, "_describe_image_file",
                        lambda p, **k: "TEK KARE (çağrılmamalı)")
    out = R._describe_clip(Path("x.mp4"), vision_call=object(), ffmpeg_path="ffmpeg")
    assert out == "an alligator lunges forward"


def test_describe_clip_storyboard_bosunca_tek_kareye_duser(tmp_path, monkeypatch):
    # storyboard kurulamaz → gerçek klipten tek kare + _describe_image_file (eski yol).
    import short_bot.reel as R
    import short_bot.footage_matcher as FM
    klip = _sentetik(tmp_path, "fb.mp4", 3)

    monkeypatch.setattr(R, "_storyboard_frames", lambda c, o, f, **k: False)
    monkeypatch.setattr(FM, "_describe_image_file", lambda p, **k: "TEK KARE DESC")
    out = R._describe_clip(klip, vision_call=object(), ffmpeg_path="ffmpeg")
    assert out == "TEK KARE DESC"
