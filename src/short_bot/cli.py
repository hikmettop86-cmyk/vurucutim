"""CLI: `python -m short_bot {init,run,list-channels}`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from short_bot.config import load_settings, load_channel, list_channels as list_chans
from short_bot.db import init_db
from short_bot.pipeline import run_pipeline


def _add_run(sub):
    p = sub.add_parser("run", help="Run pipeline for a channel")
    p.add_argument("--channel", required=True, help="Channel slug")
    p.add_argument("--max", type=int, default=1, help="Max shorts per run (default 1)")
    p.add_argument("--config-dir", default="config", help="Config root (default ./config)")
    p.add_argument("--data-dir", default="data", help="Data root (SQLite, cache, locks)")
    p.add_argument("--music-root", default="assets/music")
    p.add_argument("--templates-dir", default="templates")
    p.add_argument("--logs-dir", default="logs/runs")
    p.set_defaults(func=_cmd_run)


def _add_init(sub):
    p = sub.add_parser("init", help="Create SQLite schema")
    p.add_argument("--db-path", default="data/short_bot.sqlite")
    p.set_defaults(func=_cmd_init)


def _add_list(sub):
    p = sub.add_parser("list-channels", help="List configured channels")
    p.add_argument("--config-dir", default="config")
    p.add_argument("--enabled-only", action="store_true")
    p.set_defaults(func=_cmd_list)


def _cmd_init(args) -> int:
    init_db(Path(args.db_path))
    print(f"DB initialized: {args.db_path}")
    return 0


def _cmd_list(args) -> int:
    chans = list_chans(Path(args.config_dir) / "channels", enabled_only=args.enabled_only)
    if not chans:
        print("(no channels)")
        return 0
    print(f"{'slug':<20} {'name':<24} {'enabled':<8} cron")
    print("-" * 70)
    for c in chans:
        print(f"{c.slug:<20} {c.name:<24} {str(c.enabled):<8} {c.schedule_cron}")
    return 0


def _cmd_run(args) -> int:
    config_dir = Path(args.config_dir)
    settings = load_settings(config_dir / "settings.yaml")
    channel = load_channel(config_dir / "channels" / f"{args.channel}.yaml")

    data_dir = Path(args.data_dir)
    db_path = data_dir / "short_bot.sqlite"

    for i in range(args.max):
        print(f"--- run {i+1}/{args.max} ---")
        result = run_pipeline(
            channel=channel,
            settings=settings,
            db_path=db_path,
            music_root=Path(args.music_root),
            templates_dir=Path(args.templates_dir),
            cache_dir=data_dir / "cache",
            lock_dir=data_dir / "locks",
            logs_dir=Path(args.logs_dir),
            trigger="cli",
        )
        print(f"status={result.status} short={result.short_path} error={result.error}")
        if result.status != "success":
            return 1 if result.status == "failed" else 0
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="short-bot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    _add_run(sub)
    _add_init(sub)
    _add_list(sub)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
