"""Lightweight cron → Turkish human-readable descriptor.

Supports the standard 5-field cron strings produced by APScheduler:
    minute  hour  dom  month  dow

Examples handled:
    "0 8,14,20 * * *"  → "Her gün 08:00, 14:00, 20:00"
    "*/15 * * * *"     → "Her 15 dakikada bir"
    "0 9 * * 1-5"      → "Hafta içi her gün 09:00"
    "0 10 * * 0,6"     → "Hafta sonu her gün 10:00"

Returns the original cron string on parse failure.
"""
from __future__ import annotations


_DOW_NAMES = {0: "Pazar", 1: "Pzt", 2: "Salı", 3: "Çar",
              4: "Per", 5: "Cuma", 6: "Cmt"}


def _format_hour_minute(hours_field: str, minutes_field: str) -> str:
    if hours_field == "*" or minutes_field == "*":
        return ""
    try:
        hours = [int(h) for h in hours_field.split(",")]
        minute = int(minutes_field)
        return ", ".join(f"{h:02d}:{minute:02d}" for h in sorted(hours))
    except ValueError:
        return ""


def describe_cron(cron: str) -> str:
    """Best-effort Turkish description of a 5-field cron string."""
    parts = cron.strip().split()
    if len(parts) != 5:
        return cron
    minute, hour, dom, month, dow = parts

    # "*/N * * * *" → every N minutes
    if minute.startswith("*/") and hour == "*" and dom == "*" and month == "*" and dow == "*":
        return f"Her {minute[2:]} dakikada bir"

    # Daily
    if dom == "*" and month == "*" and dow == "*":
        times = _format_hour_minute(hour, minute)
        return f"Her gün {times}" if times else cron

    # Weekday only
    if dom == "*" and month == "*" and dow == "1-5":
        times = _format_hour_minute(hour, minute)
        return f"Hafta içi her gün {times}" if times else cron

    # Weekend
    if dom == "*" and month == "*" and dow in {"0,6", "6,0", "6,7"}:
        times = _format_hour_minute(hour, minute)
        return f"Hafta sonu her gün {times}" if times else cron

    # Specific days of week
    if dom == "*" and month == "*" and dow not in {"*", ""}:
        try:
            day_names = ", ".join(_DOW_NAMES.get(int(d), d) for d in dow.split(","))
            times = _format_hour_minute(hour, minute)
            return f"{day_names} günleri {times}" if times else cron
        except ValueError:
            return cron

    return cron


def cron_human(expr: str) -> str:
    """Convert cron expression to short Turkish human description.

    Examples:
      "0 */4 * * *" -> "Her 4 saatte bir, dakika 00"
      "0 9 * * *"   -> "Her gun saat 09:00"
      "0 9 * * 1-5" -> "Hafta ici saat 09:00"
      "*/15 * * * *" -> "15 dakikada bir"
      "0 0 1 * *"   -> "Her ayin 1'i, saat 00:00"

    Falls back to expr verbatim if pattern unrecognized.
    """
    if not expr or not expr.strip():
        return ""
    parts = expr.strip().split()
    if len(parts) != 5:
        return expr
    minute, hour, day, month, dow = parts

    # Common patterns
    if minute == "0" and hour.startswith("*/"):
        n = hour[2:]
        return f"Her {n} saatte bir, dakika 00"
    if minute.startswith("*/") and hour == "*":
        n = minute[2:]
        return f"{n} dakikada bir"
    if minute.isdigit() and hour.isdigit() and day == "*" and month == "*":
        if dow == "*":
            return f"Her gun saat {int(hour):02d}:{int(minute):02d}"
        if dow in ("1-5", "MON-FRI"):
            return f"Hafta ici saat {int(hour):02d}:{int(minute):02d}"
        if dow in ("0,6", "6,0", "SAT,SUN", "SUN,SAT"):
            return f"Hafta sonu saat {int(hour):02d}:{int(minute):02d}"
    if minute == "0" and hour == "0" and day.isdigit() and month == "*":
        return f"Her ayin {day}'i, saat 00:00"
    if hour == "*" and minute.isdigit():
        return f"Her saat dakika {int(minute):02d}"
    return expr  # fallback
