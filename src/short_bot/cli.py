"""CLI: `python -m short_bot {init,run,list-channels,create-channel}`."""
from __future__ import annotations

import argparse
import re as _re
import sys
from pathlib import Path

from short_bot.config import load_settings, load_channel, list_channels as list_chans
from short_bot.config import save_channel, ChannelConfig
from short_bot.db import init_db
from short_bot.dna import generate_dna, build_css_override
from short_bot.locale import SUPPORTED_LANGUAGES, RSS_LOCALES
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

    # CLI üretiminde reel/footage sub-logger loglarını KONSOLA bas. Panelde bunlar
    # run-log DOSYASINA gidiyor (thread-filtreli FileHandler); CLI'da run_context
    # ayarlanmadığı için filtre onları hem dosyadan hem konsoldan kesiyordu →
    # 'reel[süre]', 'render-öncesi tür kontrolü' gibi teşhis logları KAYBOLUYORDU.
    import logging as _lg

    from short_bot.pipeline import _RUN_SUB_LOGGERS
    _h = _lg.StreamHandler()
    _h.setFormatter(_lg.Formatter("[%(levelname)s] %(message)s"))
    for _n in _RUN_SUB_LOGGERS:
        _sub = _lg.getLogger(_n)
        _sub.setLevel(_lg.INFO)
        if not any(getattr(x, "_shortbot_cli", False) for x in _sub.handlers):
            _h._shortbot_cli = True
            _sub.addHandler(_h)

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


def _slug_from_name(name: str) -> str:
    import unicodedata
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = _re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return name or "channel"


def _add_create_channel(sub):
    p = sub.add_parser("create-channel", help="Create a new channel via Opus DNA generation")
    p.add_argument("--name", required=True, help='Display name (e.g. "Spor Şort DE")')
    p.add_argument("--language", required=True, help="One of: tr,en,de,es,fr")
    p.add_argument("--keywords", required=True, help="Comma-separated keyword list")
    p.add_argument("--topic-hint", default="", help="Free-form topic brief")
    p.add_argument("--target-audience", default="", help="Free-form audience brief")
    p.add_argument("--config-dir", default="config")
    p.add_argument("--templates-dir", default="templates")
    p.add_argument("--force", action="store_true", help="Overwrite existing channel")
    p.set_defaults(func=_cmd_create_channel)


def _cmd_create_channel(args) -> int:
    if args.language not in SUPPORTED_LANGUAGES:
        print(f"Error: --language must be one of {SUPPORTED_LANGUAGES}", file=sys.stderr)
        return 2
    config_dir = Path(args.config_dir)
    templates_dir = Path(args.templates_dir)
    slug = _slug_from_name(args.name)
    yaml_path = config_dir / "channels" / f"{slug}.yaml"
    css_path = templates_dir / "css" / f"{slug}.css"

    if yaml_path.exists() and not args.force:
        print(f"Error: channel '{slug}' already exists at {yaml_path}. "
              f"Use --force to overwrite.", file=sys.stderr)
        return 3

    settings = load_settings(config_dir / "settings.yaml")
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    print(f"Generating DNA via {settings.claude_models['dna']}... (this can take 30-60s)")
    try:
        dna = generate_dna(
            name=args.name, keywords=keywords, language=args.language,
            topic_hint=args.topic_hint, target_audience=args.target_audience,
            claude_path=settings.claude_cli_path,
            model=settings.claude_models.get("dna", "opus"),
        )
    except Exception as e:
        print(f"Error: DNA generation failed: {e}", file=sys.stderr)
        return 4

    print(f"  → archetype={dna.archetype}")
    print(f"  → palette: primary={dna.palette.primary} accent={dna.palette.accent}")
    print(f"  → fonts: headline={dna.fonts.headline} body={dna.fonts.body}")

    css = build_css_override(dna)
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(css, encoding="utf-8")
    print(f"  wrote {css_path}")

    cfg = ChannelConfig(
        slug=slug, name=args.name, keywords=keywords,
        rss_locale=RSS_LOCALES[args.language],
        schedule_cron="0 8,14,20 * * *",
        duration_s=6, min_score=6.0, max_candidates_per_run=10,
        template=dna.archetype,
        colors={
            "primary": dna.palette.primary,
            "accent": dna.palette.accent,
            "bg_gradient": dna.palette.bg_gradient,
        },
        handle=f"@{slug}", output_dir=f"output/{slug}",
        enabled=True,
        cta_enabled=False, cta_text="", cta_icons=[],
        cta_duration_s=0, cta_show_handle=False,
        language=args.language, dna=dna, script_model=None,
    )
    save_channel(yaml_path, cfg)
    print(f"  wrote {yaml_path}")
    print(f"\nChannel '{slug}' created. Try:\n  python -m short_bot run --channel {slug} --max 1")
    return 0


def _add_regenerate_dna(sub):
    p = sub.add_parser(
        "regenerate-dna",
        help="Re-run DNA generation for an existing channel, overwrite YAML + CSS",
    )
    p.add_argument("--channel", required=True, help="Channel slug")
    p.add_argument("--config-dir", default="config")
    p.add_argument("--templates-dir", default="templates")
    p.add_argument("--topic-hint", default="", help="Free-form topic brief")
    p.add_argument("--target-audience", default="", help="Free-form audience brief")
    p.set_defaults(func=_cmd_regenerate_dna)


def _add_rebuild_css(sub):
    p = sub.add_parser(
        "rebuild-css",
        help="Rebuild CSS from existing DNA in channel YAML (no LLM call)",
    )
    p.add_argument("--channel", required=True, help="Channel slug")
    p.add_argument("--config-dir", default="config")
    p.add_argument("--templates-dir", default="templates")
    p.set_defaults(func=_cmd_rebuild_css)


def _add_migrate_channel(sub):
    p = sub.add_parser(
        "migrate-channel",
        help="Re-save an existing channel YAML with the current schema (backward-compat migration)",
    )
    p.add_argument("--channel", required=True, help="Channel slug")
    p.add_argument("--config-dir", default="config")
    p.add_argument("--templates-dir", default="templates")
    p.add_argument(
        "--with-dna",
        action="store_true",
        help="Also regenerate DNA via LLM after migrating",
    )
    p.add_argument("--topic-hint", default="", help="Free-form topic brief (used with --with-dna)")
    p.add_argument("--target-audience", default="", help="Free-form audience brief (used with --with-dna)")
    p.set_defaults(func=_cmd_migrate_channel)


def _cmd_regenerate_dna(args) -> int:
    """Load channel, call generate_dna, write updated YAML + new CSS."""
    config_dir = Path(args.config_dir)
    templates_dir = Path(args.templates_dir)
    yaml_path = config_dir / "channels" / f"{args.channel}.yaml"

    if not yaml_path.exists():
        print(f"Error: channel '{args.channel}' not found at {yaml_path}", file=sys.stderr)
        return 1

    channel = load_channel(yaml_path)
    settings = load_settings(config_dir / "settings.yaml")

    print(f"Regenerating DNA for '{channel.name}' via {settings.claude_models.get('dna', 'opus')}...")
    try:
        dna = generate_dna(
            name=channel.name,
            keywords=list(channel.keywords),
            language=channel.language,
            topic_hint=getattr(args, "topic_hint", ""),
            target_audience=getattr(args, "target_audience", ""),
            claude_path=settings.claude_cli_path,
            model=settings.claude_models.get("dna", "opus"),
        )
    except Exception as e:
        print(f"Error: DNA generation failed: {e}", file=sys.stderr)
        return 4

    print(f"  → archetype={dna.archetype}")
    print(f"  → palette: primary={dna.palette.primary} accent={dna.palette.accent}")

    css = build_css_override(dna)
    css_path = templates_dir / "css" / f"{args.channel}.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(css, encoding="utf-8")
    print(f"  wrote {css_path}")

    # Rebuild ChannelConfig with updated DNA (use dataclasses.replace for frozen dataclass)
    import dataclasses
    updated = dataclasses.replace(
        channel,
        dna=dna,
        template=dna.archetype,
        colors={
            "primary": dna.palette.primary,
            "accent": dna.palette.accent,
            "bg_gradient": dna.palette.bg_gradient,
        },
    )
    save_channel(yaml_path, updated)
    print(f"  wrote {yaml_path}")
    return 0


def _cmd_rebuild_css(args) -> int:
    """Load channel YAML, build CSS from existing DNA — no LLM call."""
    config_dir = Path(args.config_dir)
    templates_dir = Path(args.templates_dir)
    yaml_path = config_dir / "channels" / f"{args.channel}.yaml"

    if not yaml_path.exists():
        print(f"Error: channel '{args.channel}' not found at {yaml_path}", file=sys.stderr)
        return 1

    channel = load_channel(yaml_path)

    if channel.dna is None:
        print(
            f"Error: channel '{args.channel}' has no DNA block in YAML. "
            "Run regenerate-dna first.",
            file=sys.stderr,
        )
        return 2

    css = build_css_override(channel.dna)
    css_path = templates_dir / "css" / f"{args.channel}.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(css, encoding="utf-8")
    print(f"  wrote {css_path}")
    return 0


def _cmd_migrate_channel(args) -> int:
    """Re-save channel YAML with current schema; optionally regenerate DNA with --with-dna."""
    config_dir = Path(args.config_dir)
    yaml_path = config_dir / "channels" / f"{args.channel}.yaml"

    if not yaml_path.exists():
        print(f"Error: channel '{args.channel}' not found at {yaml_path}", file=sys.stderr)
        return 1

    # load_channel handles all backward-compat (template:default → newscast, language defaults to tr)
    channel = load_channel(yaml_path)
    print(f"Loaded '{channel.name}' (slug={channel.slug}, language={channel.language}, template={channel.template})")

    if getattr(args, "with_dna", False):
        settings = load_settings(config_dir / "settings.yaml")
        print(f"Regenerating DNA via {settings.claude_models.get('dna', 'opus')}...")
        try:
            dna = generate_dna(
                name=channel.name,
                keywords=list(channel.keywords),
                language=channel.language,
                topic_hint=getattr(args, "topic_hint", ""),
                target_audience=getattr(args, "target_audience", ""),
                claude_path=settings.claude_cli_path,
                model=settings.claude_models.get("dna", "opus"),
            )
        except Exception as e:
            print(f"Error: DNA generation failed: {e}", file=sys.stderr)
            return 4

        import dataclasses
        channel = dataclasses.replace(
            channel,
            dna=dna,
            template=dna.archetype,
            colors={
                "primary": dna.palette.primary,
                "accent": dna.palette.accent,
                "bg_gradient": dna.palette.bg_gradient,
            },
        )

        templates_dir = Path(args.templates_dir)
        css = build_css_override(dna)
        css_path = templates_dir / "css" / f"{args.channel}.css"
        css_path.parent.mkdir(parents=True, exist_ok=True)
        css_path.write_text(css, encoding="utf-8")
        print(f"  wrote {css_path}")

    save_channel(yaml_path, channel)
    print(f"  wrote {yaml_path} (migrated)")
    return 0


def _add_web(sub):
    p = sub.add_parser("web", help="Start the web panel + scheduler")
    p.add_argument("--host", default=None, help="Bind host (default from settings)")
    p.add_argument("--port", type=int, default=None, help="Bind port (default from settings)")
    p.add_argument("--config-dir", default="config")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--templates-dir", default="templates")
    p.add_argument("--music-root", default="assets/music")
    p.add_argument("--logs-dir", default="logs/runs")
    p.add_argument("--output-root", default="output")
    p.add_argument("--no-scheduler", action="store_true",
                    help="Disable APScheduler (panel-only)")
    p.set_defaults(func=_cmd_web)


def _add_storyblocks_login(sub):
    p = sub.add_parser(
        "storyblocks-login",
        help="Storyblocks tarayıcı oturumu oluştur (headed Chrome ile giriş)")
    p.add_argument("--config-dir", default="config")
    p.add_argument("--session", default=None,
                   help="Oturum dosyası yolu (varsayılan: "
                        "settings.footage.storyblocks_session)")
    p.add_argument("--status", action="store_true",
                   help="Sadece oturum durumunu göster (tarayıcı açmaz)")
    p.add_argument("--delete", action="store_true",
                   help="Kayıtlı oturumu sil")
    p.set_defaults(func=_cmd_storyblocks_login)


def _cmd_storyblocks_login(args) -> int:
    from short_bot import storyblocks_login as sbl

    session = args.session
    if not session:
        try:
            settings = load_settings(Path(args.config_dir) / "settings.yaml")
            session = getattr(settings, "storyblocks_session",
                              "data/storyblocks_session.json")
        except Exception:
            session = "data/storyblocks_session.json"

    if args.status:
        st = sbl.session_status(session)
        if st["has_session"]:
            print(f"Oturum VAR: {st['path']} "
                  f"({st['size']} bayt, {st['age_seconds']}sn önce)")
        else:
            print(f"Oturum YOK: {st['path']}")
        return 0

    if args.delete:
        ok = sbl.delete_session(session)
        print("Oturum silindi." if ok else "Silinecek oturum yok.")
        return 0

    print(f"Storyblocks giriş akışı başlıyor (headed Chrome açılacak) → {session}")
    try:
        res = sbl.run_login(session)
    except Exception as e:
        print(f"Hata: {e}", file=sys.stderr)
        return 1
    print(res.get("message", ""))
    return 0 if res.get("ok") else 1


def _cmd_web(args) -> int:
    from pathlib import Path
    from short_bot.web import create_app

    config_dir = Path(args.config_dir)
    data_dir = Path(args.data_dir)
    settings = load_settings(config_dir / "settings.yaml")

    host = args.host or settings.web_host
    port = args.port or settings.web_port

    app = create_app(
        config_dir=config_dir,
        db_path=data_dir / "short_bot.sqlite",
        templates_dir=Path(args.templates_dir),
        music_root=Path(args.music_root),
        cache_dir=data_dir / "cache",
        lock_dir=data_dir / "locks",
        logs_dir=Path(args.logs_dir),
        output_root=Path(args.output_root),
        scheduler=not args.no_scheduler,
    )

    print(f"Web panel: http://{host}:{port}")
    if not args.no_scheduler:
        print(f"Scheduler: see /channels")
    print("Press Ctrl+C to stop.")
    app.run(host=host, port=port, debug=False, use_reloader=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="short-bot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    _add_run(sub)
    _add_init(sub)
    _add_list(sub)
    _add_create_channel(sub)
    _add_regenerate_dna(sub)
    _add_rebuild_css(sub)
    _add_migrate_channel(sub)
    _add_web(sub)
    _add_storyblocks_login(sub)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
