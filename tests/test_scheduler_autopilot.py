"""ÇİFTE ÜRETİM ENGELİ.

Autopilot kendi slot'larından üretiyor. Kanalın schedule_cron'u da koşarsa günde
3 yerine 6 video çıkar — ve bu HİÇBİR HATA VERMEZ. Yalnız kotayı ve kredileri yakar,
üstelik slot'suz videolar anında (public) yüklenip zamanlamayı bozar.
"""
from short_bot.web.scheduler import channel_cron_enabled


class _AP:
    def __init__(self, enabled):
        self.enabled = enabled


class _Ch:
    def __init__(self, cron="0 10 * * *", autopilot=None):
        self.slug = "k"
        self.schedule_cron = cron
        self.autopilot = autopilot


def test_autopilot_KAPALIYKEN_cron_kaydedilir():
    assert channel_cron_enabled(_Ch()) is True
    assert channel_cron_enabled(_Ch(autopilot=_AP(False))) is True


def test_autopilot_ACIKKEN_cron_KAYDEDILMEZ():
    assert channel_cron_enabled(_Ch(autopilot=_AP(True))) is False


def test_cron_bos_ise_kaydedilmez():
    assert channel_cron_enabled(_Ch(cron="")) is False
    assert channel_cron_enabled(_Ch(cron="", autopilot=_AP(True))) is False
