#!/usr/bin/env python3
"""Mirror the official Mano a Mano Megaphone RSS for Pocket Casts."""

from __future__ import annotations

import argparse
import re
import shutil
import urllib.request
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path

from config import (
    DATA_DIR,
    FEED_AUTHOR,
    FEED_DESCRIPTION,
    FEED_PATH,
    FEED_TITLE,
    PUBLIC_BASE_URL,
    SITE_DIR,
    SOURCE_FEED_URL,
    SPOTIFY_SHOW_URL,
)


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def fetch_source_feed() -> str:
    req = urllib.request.Request(
        SOURCE_FEED_URL,
        headers={
            "User-Agent": "rss-feeds/mano-a-mano (+https://github.com/wlad-c/rss-feeds)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def rewrite_feed(raw: str, public_base: str) -> tuple[str, int]:
    """Rewrite atom:self to our URL; keep Megaphone enclosures byte-for-byte otherwise."""
    base = public_base.rstrip("/")
    self_url = f"{base}/rss.xml"
    text = raw

    # Replace existing atom:link rel="self" href=...
    self_pat = re.compile(
        r'(<atom:link\b[^>]*\brel=["\']self["\'][^>]*\bhref=["\'])([^"\']+)(["\'])',
        re.IGNORECASE,
    )
    self_pat_alt = re.compile(
        r'(<atom:link\b[^>]*\bhref=["\'])([^"\']+)(["\'][^>]*\brel=["\']self["\'])',
        re.IGNORECASE,
    )
    if self_pat.search(text):
        text = self_pat.sub(rf"\g<1>{self_url}\g<3>", text, count=1)
    elif self_pat_alt.search(text):
        text = self_pat_alt.sub(rf"\g<1>{self_url}\g<3>", text, count=1)
    else:
        # Insert after <channel>
        atom_link = (
            f'<atom:link href="{self_url}" rel="self" type="application/rss+xml"/>'
        )
        text = re.sub(
            r"(<channel>\s*)",
            rf"\1{atom_link}\n    ",
            text,
            count=1,
            flags=re.IGNORECASE,
        )

    # Ensure <link> points at the Spotify show when empty/missing.
    if re.search(r"<link>\s*</link>", text, flags=re.IGNORECASE):
        text = re.sub(
            r"<link>\s*</link>",
            f"<link>{SPOTIFY_SHOW_URL}</link>",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
    elif not re.search(r"<channel>[\s\S]*?<link>", text, flags=re.IGNORECASE):
        text = re.sub(
            r"(<channel>\s*)",
            rf"\1<link>{SPOTIFY_SHOW_URL}</link>\n    ",
            text,
            count=1,
            flags=re.IGNORECASE,
        )

    stamp = format_datetime(datetime.now(tz=timezone.utc))
    if re.search(r"<lastBuildDate>.*?</lastBuildDate>", text, flags=re.IGNORECASE):
        text = re.sub(
            r"<lastBuildDate>.*?</lastBuildDate>",
            f"<lastBuildDate>{stamp}</lastBuildDate>",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        text = re.sub(
            r"(</channel>)",
            rf"    <lastBuildDate>{stamp}</lastBuildDate>\n  \1",
            text,
            count=1,
            flags=re.IGNORECASE,
        )

    episode_count = len(re.findall(r"<item\b", text, flags=re.IGNORECASE))
    return text, episode_count


def count_enclosures(rss_text: str) -> int:
    return len(re.findall(r"<enclosure\b", rss_text, flags=re.IGNORECASE))


def pocket_casts_subscribe_url(base_url: str) -> str:
    parsed_host_path = base_url.rstrip("/").removeprefix("https://").removeprefix("http://")
    return f"pktc://subscribe/{parsed_host_path}/rss.xml"


def render_index_html(episode_count: int, base_url: str) -> str:
    base = base_url.rstrip("/")
    rss = f"{base}/rss.xml"
    pktc = pocket_casts_subscribe_url(base)
    web = f"https://pocketcasts.com/follow/{rss}"
    official = SOURCE_FEED_URL
    return f"""<!doctype html>
<html lang="pt"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{escape(FEED_TITLE)} → Pocket Casts</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem;line-height:1.45}}
a.btn{{display:inline-block;margin:.4rem .4rem .4rem 0;padding:.75rem 1rem;background:#1a73e8;color:#fff;text-decoration:none;border-radius:8px;font-weight:600}}
a.btn.secondary{{background:#222}}
input{{width:100%;padding:.7rem;font-size:1rem;margin:.5rem 0 1rem;box-sizing:border-box}}
</style></head><body>
<h1>{escape(FEED_TITLE)}</h1>
<p>{escape(FEED_DESCRIPTION)}</p>
<p>Author: {escape(FEED_AUTHOR)} · {episode_count} episodes · source: <a href="{escape(SPOTIFY_SHOW_URL)}">Spotify</a></p>
<p>
  <a class="btn" href="{escape(pktc)}">Open in Pocket Casts app</a>
  <a class="btn secondary" href="{escape(web)}">Open in Pocket Casts Web</a>
</p>
<label>Paste into Pocket Casts Discover, then tap <b>Search</b>:</label>
<input readonly value="{escape(rss)}"/>
<p>Official Megaphone feed (also works in Pocket Casts):</p>
<input readonly value="{escape(official)}"/>
<p><a href="{escape(rss)}">View mirrored RSS</a> · <a href="{escape(official)}">View official RSS</a></p>
</body></html>
"""


def write_outputs(rss_text: str, episode_count: int, base_url: str) -> None:
    ensure_dirs()
    FEED_PATH.write_text(rss_text, encoding="utf-8")
    (DATA_DIR / "index.html").write_text(
        render_index_html(episode_count, base_url), encoding="utf-8"
    )


def publish_site(rss_text: str, episode_count: int, base_url: str | None = None) -> Path:
    base = (base_url or PUBLIC_BASE_URL).rstrip("/")
    write_outputs(rss_text, episode_count, base)
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / ".nojekyll").write_text("")
    (SITE_DIR / "rss.xml").write_text(rss_text, encoding="utf-8")
    (SITE_DIR / "index.html").write_text(
        render_index_html(episode_count, base), encoding="utf-8"
    )
    print(f"Published static site → {SITE_DIR} ({episode_count} episodes, base={base})")
    return SITE_DIR


def run_sync(base_url: str | None = None) -> tuple[str, int]:
    base = (base_url or PUBLIC_BASE_URL).rstrip("/")
    raw = fetch_source_feed()
    rss_text, episode_count = rewrite_feed(raw, base)
    enclosures = count_enclosures(rss_text)
    if episode_count == 0:
        raise RuntimeError("Source feed has zero <item> entries")
    if enclosures == 0:
        raise RuntimeError("Source feed has zero <enclosure> tags — not playable in Pocket Casts")
    write_outputs(rss_text, episode_count, base)
    print(
        f"Mirrored {episode_count} episodes ({enclosures} enclosures) from {SOURCE_FEED_URL}"
    )
    print(f"Wrote {FEED_PATH}")
    return rss_text, episode_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Mirror Mano a Mano → podcast RSS")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Also write a static site/mano-a-mano/ tree for gh-pages",
    )
    args = parser.parse_args()
    rss_text, episode_count = run_sync(PUBLIC_BASE_URL)
    if args.publish:
        publish_site(rss_text, episode_count, PUBLIC_BASE_URL)


if __name__ == "__main__":
    main()
