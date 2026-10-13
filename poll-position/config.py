"""Configuration for the Poll Position → Pocket Casts feed."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
MEDIA_DIR = DATA_DIR / "media"
STATE_PATH = DATA_DIR / "state.json"
FEED_PATH = DATA_DIR / "rss.xml"

# The Star's labelled Poll Position playlist on YouTube.
YOUTUBE_PLAYLIST_ID = os.environ.get("YOUTUBE_PLAYLIST_ID", "PLUl1gfNnrZcc")
YOUTUBE_PLAYLIST_URL = f"https://www.youtube.com/playlist?list={YOUTUBE_PLAYLIST_ID}"

# Same episodes are published on Dailymotion (easier audio extract than YouTube).
DAILYMOTION_USER = os.environ.get("DAILYMOTION_USER", "thestar")
TITLE_FILTER = os.environ.get("TITLE_FILTER", "Poll Position")

def _default_public_base_url() -> str:
    """Prefer GitHub Pages URL when running in Actions / when repo is known."""
    explicit = os.environ.get("PUBLIC_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY")  # e.g. wlad-c/rss-feeds
    if repo and "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}"
    return "http://127.0.0.1:8787"


PUBLIC_BASE_URL = _default_public_base_url()
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8787"))
SYNC_INTERVAL_SECONDS = int(os.environ.get("SYNC_INTERVAL_SECONDS", str(60 * 60)))
SITE_DIR = Path(os.environ.get("SITE_DIR", ROOT / "site"))

FEED_TITLE = "Poll Position (The Star)"
FEED_AUTHOR = "The Star"
FEED_EMAIL = "podcasts@thestar.com.my"
FEED_DESCRIPTION = (
    "Automatic podcast feed of The Star's Poll Position videos — "
    "Malaysian politics and state election analysis with Philip Golingai and guests."
)
FEED_LANGUAGE = "en"
FEED_CATEGORY = "News"
FEED_COPYRIGHT = "The Star"
