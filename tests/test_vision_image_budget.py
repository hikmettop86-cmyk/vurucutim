"""256KB'ı aşan görsel CLI'ye İLİŞTİRİLMİYOR — yargıç KÖR karar veriyor.

GERÇEK HATA (short 1077): final QA storyboard'u 324KB'tı. `claude -p` bu görseli
sessizce düşürdü; modele yalnızca dosya YOLU ve anlatım metni gitti. Sonuç iki
türlü çıktı, ikisi de zararlı:
  • boş/araç-çağrısı yanıt ({"file_path": "...board.jpg"}) → şema doğrulanmadı →
    kapı None aldı → fail-open (video yargılanmadan yayına uygun sayıldı),
  • ya da GÜVENLE UYDURULMUŞ hüküm: "senkron=True, skor 8, kep örtme anları
    anlatımla birebir örtüşüyor" — oysa o saniyelerde ekranda fuaye vardı.
İkincisi daha tehlikeli: kapı çalışıyor görünürken hiçbir şey görmüyor.

ÖLÇÜM (aynı pano, farklı sıkıştırma; 2'şer çağrı):
    239.437 bayt → 2/2 yanıt        286.262 bayt → 0/2 yanıt
Sınır 262.144 (256KB). Kural: bütçeyi aşan görsel KÜÇÜLTÜLÜR; küçültülemiyorsa
hata verilir — kör yargı vermektense patlamak yeğdir.
"""
import os
import subprocess

import pytest

from short_bot import claude_cli
from short_bot.claude_cli import CLI_IMAGE_MAX_BYTES, ClaudeCliError


def _noisy_jpeg(path, w=1152, h=2049):
    """Sıkıştırılamayan gürültü → bütçeyi kesin aşan gerçek bir JPEG."""
    from PIL import Image
    img = Image.frombytes("RGB", (w, h), os.urandom(w * h * 3))
    img.save(path, "JPEG", quality=95)
    return path


class _Proc:
    returncode = 0
    stdout = '{"ok": true}'
    stderr = ""


def _capture_cli(monkeypatch):
    """subprocess.run'ı yakala. Ölçüm ÇAĞRI ANINDA yapılır: küçültülmüş kopya
    geçici dizinde yaşar ve çağrı dönünce silinir — CLI'nin gördüğü dosya budur."""
    from PIL import Image
    seen = {}

    def fake_run(cmd, **kw):
        prompt = kw.get("input", "")
        first = prompt.splitlines()[0]
        assert first.startswith("@"), f"görsel iliştirilmemiş: {first!r}"
        path = first[1:]
        seen["path"] = path
        seen["size"] = os.path.getsize(path)
        with Image.open(path) as im:
            im.verify()                      # bozuk JPEG değil
        return _Proc()

    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)
    return seen


def test_oversized_image_is_shrunk_before_reaching_cli(tmp_path, monkeypatch):
    """Bütçeyi aşan görsel KÜÇÜLTÜLÜP gönderilir — sessizce düşmesin."""
    big = _noisy_jpeg(tmp_path / "big.jpg")
    assert big.stat().st_size > CLI_IMAGE_MAX_BYTES, "test görseli zaten bütçe altında"
    seen = _capture_cli(monkeypatch)

    claude_cli._invoke_primary("soru", backend="claude_cli", model="default",
                               claude_path="claude", api_key=None, timeout_s=30,
                               image_path=big)

    assert seen["size"] <= CLI_IMAGE_MAX_BYTES, "hâlâ bütçe üstü gönderiliyor"
    # (geçerli/okunur JPEG olduğu _capture_cli içinde doğrulandı — yargıç ona bakacak)


def test_small_image_is_passed_through_untouched(tmp_path, monkeypatch):
    """Bütçe altındaki görsele DOKUNMA (gereksiz kalite kaybı yok)."""
    from PIL import Image
    small = tmp_path / "small.jpg"
    Image.new("RGB", (600, 400), (10, 20, 90)).save(small, "JPEG", quality=88)
    seen = _capture_cli(monkeypatch)

    claude_cli._invoke_primary("soru", backend="claude_cli", model="default",
                               claude_path="claude", api_key=None, timeout_s=30,
                               image_path=small)

    assert seen["path"] == small.absolute().as_posix()


def test_unshrinkable_image_raises_instead_of_judging_blind(tmp_path, monkeypatch):
    """Bütçeye indirilemiyorsa GÖNDERME — kör yargıdansa hata."""
    monkeypatch.setattr(claude_cli, "CLI_IMAGE_MAX_BYTES", 64)   # ulaşılamaz bütçe
    big = _noisy_jpeg(tmp_path / "big.jpg", w=800, h=1400)
    called = {"n": 0}

    def fake_run(cmd, **kw):
        called["n"] += 1
        return _Proc()

    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)

    with pytest.raises(ClaudeCliError, match="görsel"):
        claude_cli._invoke_primary("soru", backend="claude_cli", model="default",
                                   claude_path="claude", api_key=None, timeout_s=30,
                                   image_path=big)
    assert called["n"] == 0, "kör yargı için yine de CLI çağrıldı"


def test_storyboard_stays_under_budget(tmp_path):
    """Yargıçların panosu bütçeyi AŞMAMALI (kaynağı ne olursa olsun)."""
    from short_bot.reel import _storyboard_frames
    clip = tmp_path / "noise.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "nullsrc=s=640x1136:d=6:r=10",
                    "-vf", "geq=random(1)*255:128:128", "-c:v", "libx264",
                    "-crf", "18", "-pix_fmt", "yuv420p", str(clip)],
                   capture_output=True, timeout=120)
    if not clip.exists() or clip.stat().st_size == 0:
        pytest.skip("ffmpeg yok/klip üretilemedi")

    board = tmp_path / "board.jpg"
    assert _storyboard_frames(clip, board, "ffmpeg", cols=3, rows=3, frame_w=384)
    assert board.stat().st_size <= CLI_IMAGE_MAX_BYTES, (
        f"pano {board.stat().st_size} bayt — CLI bunu sessizce düşürür")
