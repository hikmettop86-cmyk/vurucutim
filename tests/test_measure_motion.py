"""Statik footage tespiti (donmuş kuyruk önleme, short 818)."""


def test_measure_motion_bos_klip_fail_open(tmp_path):
    """Okunamayan/olmayan klip → 1.0 (hareketli varsay, iyi klibi eleme)."""
    from short_bot.reel_grade import measure_motion
    assert measure_motion(tmp_path / "yok.mp4") == 1.0


def test_motion_min_esik_makul():
    from short_bot.reel_grade import MOTION_MIN
    # statik ~0.003, hareketli ~0.02+ (ölçüldü) — eşik arada
    assert 0.005 <= MOTION_MIN <= 0.015


def test_measure_motion_deger_araligi():
    """Sentetik: tam donuk (tek renk) klip → düşük; renk değişen → yüksek."""
    import subprocess, tempfile
    from pathlib import Path
    from short_bot.reel_grade import measure_motion
    td = Path(tempfile.mkdtemp())
    donuk = td / "donuk.mp4"
    hareketli = td / "hareketli.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=gray:s=128x128:d=4:r=10", "-c:v", "libx264",
                    str(donuk), "-y"], timeout=30)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=s=128x128:d=4:r=10", "-c:v", "libx264",
                    str(hareketli), "-y"], timeout=30)
    m_donuk = measure_motion(donuk)
    m_hareketli = measure_motion(hareketli)
    assert m_donuk < m_hareketli
    assert m_donuk < 0.008          # tam donuk statik sayılır
