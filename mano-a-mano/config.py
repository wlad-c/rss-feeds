"""Configuration for the Mano a Mano → Pocket Casts feed mirror."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data" / "mano-a-mano"))
FEED_PATH = DATA_DIR / "rss.xml"
SITE_DIR = Path(os.environ.get("SITE_DIR", ROOT / "site" / "mano-a-mano"))

# Official Spotify Studios / Megaphone feed for the Spotify show
# https://open.spotify.com/show/0GnKiYeK11476CfoQEYlEd
SOURCE_FEED_URL = os.environ.get(
    "SOURCE_FEED_URL", "https://feeds.megaphone.fm/GLT5279624272"
)
SPOTIFY_SHOW_URL = "https://open.spotify.com/show/0GnKiYeK11476CfoQEYlEd"
SPOTIFY_SHOW_ID = "0GnKiYeK11476CfoQEYlEd"


def _default_public_base_url() -> str:
    """Prefer jsDelivr→feeds CDN URL (tiny branch; no Poll Position media)."""
    explicit = os.environ.get("PUBLIC_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY")  # e.g. wlad-c/rss-feeds
    if repo and "/" in repo:
        # Dedicated lightweight branch — avoids jsDelivr's 50MB package limit
        # that breaks @gh-pages because Poll Position media is ~122MB.
        return f"https://cdn.jsdelivr.net/gh/{repo}@feeds/mano-a-mano"
    return "http://127.0.0.1:8787/mano-a-mano"


PUBLIC_BASE_URL = _default_public_base_url()

FEED_TITLE = "Mano a Mano"
FEED_AUTHOR = "Spotify Studios"
FEED_DESCRIPTION = (
    "Salve, rapa! Salve, massa! Mano Brown vem para ampliar a visão e o debate "
    "trazendo diversidade de ideias e pensamentos com profundidade e respeito. "
    "Um Original Spotify — mirrored for Pocket Casts."
)
