"""Autopilot ayarları.

VARSAYILAN KAPALI ve bu kasıtlı: açık gelen bir otomasyon, kullanıcının hiç istemediği
videoları hiç istemediği saatlerde yayınlar.
"""
import pytest
from pydantic import ValidationError

from short_bot.autopilot import MIN_SLOT_GAP_MIN
from short_bot.config import AutopilotConfig, load_channel, save_channel

_YAML = """slug: k
name: Kanal
keywords: [x]
language: tr
schedule_cron: "0 10 * * *"
duration_s: 40
min_score: 7.0
max_candidates_per_run: 3
max_age_hours: 24
template: stat-hero
colors: {primary: '#000000', accent: '#ffffff', bg_gradient: ['#000000', '#111111']}
handle: '@k'
output_dir: output/k
enabled: true
content_source: generator
generator: {topic: 'ilginc bilgiler burada'}
"""


def test_varsayilan_KAPALI():
    assert AutopilotConfig().enabled is False


def test_varsayilanlar_makul():
    c = AutopilotConfig()
    assert c.daily_count == 3
    assert c.active_hours == (10, 22)
    assert c.timezone == "Europe/Istanbul"
    assert c.publish_mode == "publish_at"
    assert c.produce_lead_hours >= 1
    assert c.max_attempts >= 2


def test_ters_aktif_saat_REDDEDILIR():
    with pytest.raises(ValidationError):
        AutopilotConfig(active_hours=(22, 10))
    with pytest.raises(ValidationError):
        AutopilotConfig(active_hours=(10, 10))


def test_slotlar_SIGMIYORSA_reddedilir():
    """12 slot / 2 saat → slotlar 10 dakika arayla. Bu 'insan' değil, ve
    MIN_SLOT_GAP_MIN koruması hepsini üst üste iterdi (sessiz bozulma)."""
    with pytest.raises(ValidationError):
        AutopilotConfig(active_hours=(10, 12), daily_count=12)


def test_sigan_yapilandirma_kabul():
    c = AutopilotConfig(active_hours=(10, 22), daily_count=6)
    assert (22 - 10) * 60 / c.daily_count >= MIN_SLOT_GAP_MIN


def test_gecersiz_saat_dilimi_REDDEDILIR():
    with pytest.raises(ValidationError):
        AutopilotConfig(timezone="Mars/Olympus")


def test_gecerli_saat_dilimleri_kabul():
    for tz in ("Europe/Istanbul", "Europe/Berlin", "UTC", "America/New_York"):
        assert AutopilotConfig(timezone=tz).timezone == tz


def test_yaml_yoksa_autopilot_None(tmp_path):
    p = tmp_path / "k.yaml"
    p.write_text(_YAML, encoding="utf-8")
    assert load_channel(p).autopilot is None


def test_yaml_gidis_donus(tmp_path):
    p = tmp_path / "k.yaml"
    p.write_text(_YAML + "autopilot:\n  enabled: true\n  daily_count: 2\n"
                         "  publish_mode: live_upload\n  produce_lead_hours: 2\n",
                 encoding="utf-8")
    cfg = load_channel(p)
    assert cfg.autopilot.enabled is True
    assert cfg.autopilot.daily_count == 2
    assert cfg.autopilot.publish_mode == "live_upload"
    assert cfg.autopilot.produce_lead_hours == 2

    save_channel(p, cfg)
    tekrar = load_channel(p)
    assert tekrar.autopilot == cfg.autopilot, "kaydet→yükle ayarı KAYBETMEMELİ"


def test_autopilot_YOKKEN_kaydet_yukle_hala_None(tmp_path):
    """Geriye uyum: autopilot bloğu olmayan kanal, kaydedilince blok KAZANMAMALI."""
    p = tmp_path / "k.yaml"
    p.write_text(_YAML, encoding="utf-8")
    cfg = load_channel(p)
    save_channel(p, cfg)
    assert load_channel(p).autopilot is None
