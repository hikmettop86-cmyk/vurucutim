"""Pexels Videos API client + archetype-pool query selector + secret resolver."""
from __future__ import annotations

import os
import random
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


ARCHETYPE_BG_QUERIES: dict[str, list[str]] = {
    "newscast":  ["newsroom blur", "studio lights motion", "news ticker abstract"],
    "tabloid":   ["paparazzi flash", "neon city night", "magazine pages turning"],
    "magazine":  ["soft fabric texture", "ink water swirl", "warm bokeh"],
    "kinetic":   ["geometric motion", "abstract neon lines", "particle wave"],
    "dark-tech": ["circuit board glow", "matrix code rain", "server room cyan"],
    "stadium":   ["stadium lights night", "crowd cheering blur", "grass pitch zoom"],
    "meme":      ["confetti pop", "colorful gradient swirl", "cartoon background"],
}


def pick_query_for_archetype(archetype: str) -> str:
    """Random pick from the pool. Unknown archetype → generic fallback."""
    pool = ARCHETYPE_BG_QUERIES.get(archetype)
    if not pool:
        return "abstract motion background"
    return random.choice(pool)
