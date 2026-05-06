"""Pexels Videos API client + archetype-pool query selector + secret resolver."""
from __future__ import annotations

import os
from pathlib import Path

import yaml


def load_secrets(secrets_path: Path) -> dict:
    """Return parsed YAML dict from secrets_path, or {} if file missing/empty."""
    p = Path(secrets_path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def resolve_pexels_api_key(secrets: dict) -> str:
    """Resolve the Pexels API key. Env var PEXELS_API_KEY beats secrets dict."""
    return os.environ.get("PEXELS_API_KEY") or secrets.get("pexels_api_key") or ""
