"""Tarayici render'in ORTASINDA kapanirsa video kaybedilmemeli.

CANLI VAKA (2026-08-09, panel kosusu #1587 ve iki CLI kosusu):
  Page.screenshot: Target page, context or browser has been closed

Makinede baska bir otomasyon da Playwright kullaniyor. 6 saniyelik videolar
180 kare oldugu icin aradan siyriliyordu; SESLENDIRMELI videolar 1000+ kare
surdugu icin o pencereye yakalaniyor ve TUM uretim olüyordu -- oysa o ana kadar
basilan yuzlerce kare diskte hazir duruyor.

Cozum ai33 poll'undeki ile ayni felsefe: gecici bir kopma isi TERK ETTIRMEZ.
Tarayici yeniden acilir ve KALDIGI KAREDEN devam edilir.
"""
from pathlib import Path

import pytest

from short_bot import renderer


class _SahtePage:
    """N kare bastiktan sonra tarayici kopmasini taklit eder."""

    def __init__(self, kir_at: int | None, sayac: dict):
        self._kir_at = kir_at
        self._sayac = sayac

    def set_content(self, *a, **k):
        pass

    def evaluate(self, *a, **k):
        pass

    def add_init_script(self, *a, **k):
        pass

    def screenshot(self, *, path, **k):
        if self._kir_at is not None and self._sayac["basilan"] >= self._kir_at:
            raise RuntimeError(
                "Page.screenshot: Target page, context or browser has been closed")
        Path(path).write_bytes(b"png")
        self._sayac["basilan"] += 1


class _SahteBrowser:
    def __init__(self, page):
        self._page = page

    def new_page(self, **k):
        return self._page

    def close(self):
        pass


class _SahtePlaywright:
    def __init__(self, sayfalar):
        self._sayfalar = list(sayfalar)
        self.acilis = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def chromium(self):
        return self

    def launch(self, **k):
        self.acilis += 1
        return _SahteBrowser(self._sayfalar.pop(0))


def _job(frames: int, fps: int = 30):
    class _J:
        script = None
        narration = None
        duration_s = frames / fps
    return _J()


def test_tarayici_kopunca_kaldigi_kareden_devam_eder(monkeypatch, tmp_path):
    sayac = {"basilan": 0}
    # 1. oturum 40 karede kopar, 2. oturum sonuna kadar gider.
    sahte = _SahtePlaywright([_SahtePage(40, sayac), _SahtePage(None, sayac)])
    monkeypatch.setattr(renderer, "sync_playwright", lambda: sahte)
    monkeypatch.setattr(renderer, "build_html", lambda *a, **k: "<html></html>")
    monkeypatch.setattr(renderer, "_total_frames", lambda job, fps: 100)

    n = renderer.render_frames(_job(100), Path("t.j2"), tmp_path, fps=30)

    assert n == 100
    assert sahte.acilis == 2, "tarayici yeniden acilmadi"
    uretilen = sorted(p.name for p in tmp_path.glob("frame_*.png"))
    assert len(uretilen) == 100, f"eksik kare: {len(uretilen)}"
    assert uretilen[0] == "frame_00000.png" and uretilen[-1] == "frame_00099.png"


def test_surekli_kopma_sonsuz_donguye_girmez(monkeypatch, tmp_path):
    """Her oturum aninda koparsa vazgecilmeli -- sonsuz yeniden deneme olmaz."""
    sayac = {"basilan": 0}
    sahte = _SahtePlaywright([_SahtePage(0, sayac) for _ in range(20)])
    monkeypatch.setattr(renderer, "sync_playwright", lambda: sahte)
    monkeypatch.setattr(renderer, "build_html", lambda *a, **k: "<html></html>")
    monkeypatch.setattr(renderer, "_total_frames", lambda job, fps: 50)

    with pytest.raises(RuntimeError):
        renderer.render_frames(_job(50), Path("t.j2"), tmp_path, fps=30)
    assert sahte.acilis <= 5, "cok fazla yeniden deneme"


def test_kopma_yoksa_tek_oturumda_biter(monkeypatch, tmp_path):
    sayac = {"basilan": 0}
    sahte = _SahtePlaywright([_SahtePage(None, sayac)])
    monkeypatch.setattr(renderer, "sync_playwright", lambda: sahte)
    monkeypatch.setattr(renderer, "build_html", lambda *a, **k: "<html></html>")
    monkeypatch.setattr(renderer, "_total_frames", lambda job, fps: 30)

    assert renderer.render_frames(_job(30), Path("t.j2"), tmp_path, fps=30) == 30
    assert sahte.acilis == 1
