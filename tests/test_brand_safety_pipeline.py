"""brand_safety kanal ayarı ve boru hattı bağlantısı."""
from __future__ import annotations

import inspect

import pytest
import yaml


def _yaz(tmp_path, **extra):
    data = {
        "slug": "bs-test", "name": "T", "keywords": ["a"], "language": "tr",
        "schedule_cron": "0 9 * * *", "duration_s": 6, "min_score": 6.0,
        "max_candidates_per_run": 10, "max_age_hours": 24, "template": "flas",
        "colors": {"primary": "#d0021b", "accent": "#ffe600",
                   "bg_gradient": ["#111111", "#222222"]},
        "handle": "@t", "output_dir": "o", "content_source": "trends",
    }
    data.update(extra)
    p = tmp_path / "bs-test.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def test_varsayilan_kapali(tmp_path):
    """Mevcut kanalların davranışı SESSİZCE değişmemeli."""
    from short_bot.config import load_channel
    assert load_channel(_yaz(tmp_path)).brand_safety == "off"


def test_seviye_okunur(tmp_path):
    from short_bot.config import load_channel
    assert load_channel(_yaz(tmp_path, brand_safety="strict")).brand_safety == "strict"


def test_gecersiz_seviye_sessizce_dusmez(tmp_path):
    from short_bot.config import load_channel
    with pytest.raises(ValueError, match="brand_safety"):
        load_channel(_yaz(tmp_path, brand_safety="siki"))


def test_kaydedilince_yamlda_kalir(tmp_path):
    from short_bot.config import load_channel, save_channel
    cfg = load_channel(_yaz(tmp_path, brand_safety="normal"))
    out = tmp_path / "k.yaml"
    save_channel(out, cfg)
    assert yaml.safe_load(out.read_text(encoding="utf-8"))["brand_safety"] == "normal"


def test_kapaliyken_yamla_yazilmaz(tmp_path):
    from short_bot.config import load_channel, save_channel
    cfg = load_channel(_yaz(tmp_path))
    out = tmp_path / "k.yaml"
    save_channel(out, cfg)
    assert "brand_safety" not in yaml.safe_load(out.read_text(encoding="utf-8"))


def test_boru_hatti_suzgeci_cagiriyor():
    from short_bot import pipeline
    src = inspect.getsource(pipeline._run_rss)
    assert "brand_safety" in src and "risk_of" in src


def test_suzgec_sessiz_degil():
    """Elenen haber loglanmalı — sessiz süzme, kaynağı görünmez bir boşluktur."""
    from short_bot import pipeline
    src = inspect.getsource(pipeline._run_rss)
    assert "marka güvenliği" in src


def test_trends_baglam_satiri_taranmaz():
    """CANLI YANLIŞ POZİTİF (2026-08-22): trends haberinin `description` alanı
    Trends BAĞLAM satırıdır — ilişkili aramalar ve BAŞKA makalelerin başlıkları.
    Kardeş bir makalede 性的関係 geçtiği için yaşlı BAKIM haberi 'cinsel' diye
    elendi.

    Gövde o aşamada henüz çıkarılmamış (extract_article seçimden SONRA koşar),
    yani description'ı taramak hiçbir zaman gövdeyi taramıyordu."""
    from short_bot import pipeline
    import inspect
    src = inspect.getsource(pipeline._run_rss)
    i = src.index("marka güvenliği")
    blok = src[i:i + 900]
    assert "it.description" not in blok, "hâlâ Trends bağlam satırı taranıyor"
    assert "it.title" in blok
