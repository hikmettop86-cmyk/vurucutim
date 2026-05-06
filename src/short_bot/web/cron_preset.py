"""UI-friendly cron preset shortcuts.

Backend stores ChannelConfig.schedule_cron as a cron string. The UI offers
a dropdown (hourly / every_2h / daily-with-hour / weekly-with-day-and-hour /
custom) and round-trips through these helpers.
"""
import re

_DAILY_RE = re.compile(r"^daily_(\d{2})$")
_WEEKLY_RE = re.compile(r"^weekly_([0-6])_(\d{2})$")


def preset_to_cron(preset: str) -> str | None:
    """Return cron string for a preset, or None if 'custom' or invalid."""
    if preset == "hourly":
        return "0 * * * *"
    if preset == "every_2h":
        return "0 */2 * * *"
    if preset == "custom":
        return None
    m = _DAILY_RE.match(preset)
    if m:
        hour = int(m.group(1))
        if 0 <= hour <= 23:
            return f"0 {hour} * * *"
        return None
    m = _WEEKLY_RE.match(preset)
    if m:
        dow = int(m.group(1))
        hour = int(m.group(2))
        if 0 <= dow <= 6 and 0 <= hour <= 23:
            return f"0 {hour} * * {dow}"
        return None
    return None


_CRON_HOURLY = "0 * * * *"
_CRON_EVERY_2H = "0 */2 * * *"
_DAILY_CRON_RE = re.compile(r"^0 (\d{1,2}) \* \* \*$")
_WEEKLY_CRON_RE = re.compile(r"^0 (\d{1,2}) \* \* (\d)$")


def cron_to_preset(cron: str) -> str:
    """Best-effort reverse: cron string → preset code. 'custom' if no match."""
    if cron == _CRON_HOURLY:
        return "hourly"
    if cron == _CRON_EVERY_2H:
        return "every_2h"
    m = _DAILY_CRON_RE.match(cron)
    if m:
        return f"daily_{int(m.group(1)):02d}"
    m = _WEEKLY_CRON_RE.match(cron)
    if m:
        return f"weekly_{m.group(2)}_{int(m.group(1)):02d}"
    return "custom"
