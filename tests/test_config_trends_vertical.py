"""trends_vertical / trends_min_candidates — YAML gidiş-dönüşü ve doğrulama."""
from __future__ import annotations

import pytest
import yaml


def _yaz(tmp_path, **extra):
    data = {
        "slug": "test-dikey", "name": "Test", "keywords": ["a"], "language": "tr",
        "schedule_cron": "0 9 * * *", "duration_s": 6, "min_score": 6.0,
        "max_candidates_per_run": 10, "max_age_hours": 24, "template": "flas",
        "colors": {"primary": "#fff", "accent": "#000", "bg_gradient": ["#111", "#222"]},
        "handle": "@t", "output_dir": "output/t", "content_source": "trends",
    }
    data.update(extra)
    p = tmp_path / "test-dikey.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def test_varsayilan_dikey_yok(tmp_path):
    from short_bot.config import load_channel
    cfg = load_channel(_yaz(tmp_path))
    assert cfg.trends_vertical is None
    assert cfg.trends_min_candidates == 4


def test_dikey_okunur(tmp_path):
    from short_bot.config import load_channel
    cfg = load_channel(_yaz(tmp_path, trends_vertical="para"))
    assert cfg.trends_vertical == "para"


def test_gecersiz_dikey_sessizce_dusmez(tmp_path):
    from short_bot.config import load_channel
    with pytest.raises(ValueError, match="trends_vertical"):
        load_channel(_yaz(tmp_path, trends_vertical="futbol"))


def test_dikey_kaydedilince_yamlda_kalir(tmp_path):
    from short_bot.config import load_channel, save_channel
    p = _yaz(tmp_path, trends_vertical="adalet", trends_min_candidates=6)
    cfg = load_channel(p)
    out = tmp_path / "kayit.yaml"
    save_channel(out, cfg)
    geri = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert geri["trends_vertical"] == "adalet"
    assert geri["trends_min_candidates"] == 6


def test_dikeysiz_kanal_yamlda_alan_yazmaz(tmp_path):
    from short_bot.config import load_channel, save_channel
    cfg = load_channel(_yaz(tmp_path))
    out = tmp_path / "kayit.yaml"
    save_channel(out, cfg)
    geri = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert "trends_vertical" not in geri
    assert "trends_min_candidates" not in geri
