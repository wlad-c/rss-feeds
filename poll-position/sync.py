#!/usr/bin/env python3
"""Sync The Star Poll Position videos into a Pocket Casts–ready podcast feed."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from email.utils import format_datetime
from html import escape
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from config import (
    DAILYMOTION_USER,
    DATA_DIR,
    FEED_AUTHOR,
    FEED_CATEGORY,
    FEED_COPYRIGHT,
    FEED_DESCRIPTION,
    FEED_EMAIL,
    FEED_LANGUAGE,
    FEED_PATH,
    FEED_TITLE,
    MEDIA_DIR,
    PUBLIC_BASE_URL,
    STATE_PATH,
    TITLE_FILTER,
    YOUTUBE_PLAYLIST_URL,
)


@dataclass
class Episode:
    youtube_id: str
    dailymotion_id: str
    title: str
    description: str
    duration_seconds: int
    published: str  # RFC 2822
    thumbnail: str
    youtube_url: str
    media_file: str
    media_bytes: int


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def normalize_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"poll\s*position[:\-]?\s*", " ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def fetch_dailymotion_episodes() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    page = 1
    needle = TITLE_FILTER.lower()
    while page <= 10:
        qs = urllib.parse.urlencode(
            {
                "search": TITLE_FILTER,
                "fields": "id,title,description,duration,created_time,thumbnail_720_url,thumbnail_url,url",
                "limit": 100,
                "page": page,
            }
        )
        url = f"https://api.dailymotion.com/user/{DAILYMOTION_USER}/videos?{qs}"
        with urllib.request.urlopen(url, timeout=60) as resp:
            payload = json.load(resp)
        for item in payload.get("list", []):
            if needle in (item.get("title") or "").lower():
                results.append(item)
        if not payload.get("has_more"):
            break
        page += 1
    return results


def fetch_youtube_playlist() -> list[dict[str, Any]]:
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--flat-playlist",
        "--dump-single-json",
        YOUTUBE_PLAYLIST_URL,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp playlist fetch failed:\n{proc.stderr}")
    data = json.loads(proc.stdout)
    entries = []
    for entry in data.get("entries") or []:
        if not entry:
            continue
        vid = entry.get("id")
        title = entry.get("title") or ""
        if not vid or TITLE_FILTER.lower() not in title.lower():
            continue
        entries.append(
            {
                "id": vid,
                "title": title,
                "description": entry.get("description") or "",
                "duration": int(entry.get("duration") or 0),
                "timestamp": entry.get("timestamp"),
                "upload_date": entry.get("upload_date"),
                "thumbnails": entry.get("thumbnails") or [],
                "url": entry.get("url") or f"https://www.youtube.com/watch?v={vid}",
            }
        )
    return entries


def best_dm_match(yt_title: str, dm_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    target = normalize_title(yt_title)
    best = None
    best_score = 0.0
    for item in dm_items:
        score = SequenceMatcher(None, target, normalize_title(item.get("title") or "")).ratio()
        if score > best_score:
            best_score = score
            best = item
    if best is not None and best_score >= 0.45:
        return best
    # Fallback: exact substring either way after normalization.
    for item in dm_items:
        a = normalize_title(yt_title)
        b = normalize_title(item.get("title") or "")
        if a and b and (a in b or b in a):
            return item
    return None


def published_rfc2822(yt: dict[str, Any], dm: dict[str, Any]) -> str:
    ts = yt.get("timestamp")
    if not ts and yt.get("upload_date"):
        try:
            dt = datetime.strptime(yt["upload_date"], "%Y%m%d").replace(tzinfo=timezone.utc)
            return format_datetime(dt)
        except ValueError:
            pass
    if ts:
        return format_datetime(datetime.fromtimestamp(int(ts), tz=timezone.utc))
    created = dm.get("created_time")
    if created:
        return format_datetime(datetime.fromtimestamp(int(created), tz=timezone.utc))
    return format_datetime(datetime.now(tz=timezone.utc))


def thumbnail_for(yt: dict[str, Any], dm: dict[str, Any]) -> str:
    thumbs = yt.get("thumbnails") or []
    if thumbs:
        return thumbs[-1].get("url") or f"https://i.ytimg.com/vi/{yt['id']}/hqdefault.jpg"
    return (
        dm.get("thumbnail_720_url")
        or dm.get("thumbnail_url")
        or f"https://i.ytimg.com/vi/{yt['id']}/hqdefault.jpg"
    )


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def download_mp3(dailymotion_id: str, dest: Path) -> int:
    if dest.exists() and dest.stat().st_size > 0:
        return dest.stat().st_size
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_template = str(dest.with_suffix("")) + ".%(ext)s"
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "-f",
        "hls-380/worst",
        "-x",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "5",
        "--impersonate",
        "chrome",
        "-o",
        tmp_template,
        f"https://www.dailymotion.com/video/{dailymotion_id}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not dest.exists():
        raise RuntimeError(
            f"Failed to download {dailymotion_id}:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return dest.stat().st_size


def build_description(yt: dict[str, Any], dm: dict[str, Any], youtube_url: str) -> str:
    desc = (yt.get("description") or "").strip()
    if not desc:
        desc = (dm.get("description") or "").strip()
    if not desc:
        desc = yt.get("title") or dm.get("title") or ""
    if "Watch on YouTube:" not in desc:
        desc = f"{desc}\n\nWatch on YouTube: {youtube_url}".strip()
    return desc


def sync_episodes() -> list[Episode]:
    ensure_dirs()
    yt_entries = fetch_youtube_playlist()
    dm_items = fetch_dailymotion_episodes()
    if not yt_entries:
        raise RuntimeError("No Poll Position videos found on the YouTube playlist.")
    if not dm_items:
        raise RuntimeError("No Poll Position videos found on Dailymotion.")

    episodes: list[Episode] = []
    for yt in yt_entries:
        dm = best_dm_match(yt["title"], dm_items)
        if not dm:
            print(f"WARN: no Dailymotion match for {yt['id']} {yt['title']}", file=sys.stderr)
            continue
        media_name = f"{dm['id']}.mp3"
        media_path = MEDIA_DIR / media_name
        print(f"Syncing {yt['title']} → {media_name}", flush=True)
        size = download_mp3(dm["id"], media_path)
        youtube_url = f"https://www.youtube.com/watch?v={yt['id']}"
        duration = int(yt.get("duration") or dm.get("duration") or 0)
        episodes.append(
            Episode(
                youtube_id=yt["id"],
                dailymotion_id=dm["id"],
                title=yt["title"],
                description=build_description(yt, dm, youtube_url),
                duration_seconds=duration,
                published=published_rfc2822(yt, dm),
                thumbnail=thumbnail_for(yt, dm),
                youtube_url=youtube_url,
                media_file=media_name,
                media_bytes=size,
            )
        )

    # Newest first for podcast clients.
    def sort_key(ep: Episode) -> float:
        try:
            return datetime.strptime(ep.published, "%a, %d %b %Y %H:%M:%S %z").timestamp()
        except ValueError:
            return 0.0

    episodes.sort(key=sort_key, reverse=True)
    return episodes


def render_rss(episodes: list[Episode], base_url: str) -> str:
    base = base_url.rstrip("/")
    self_url = f"{base}/rss.xml"
    cover = episodes[0].thumbnail if episodes else f"{base}/"
    last_build = format_datetime(datetime.now(tz=timezone.utc))
    items_xml: list[str] = []
    for ep in episodes:
        enclosure = f"{base}/media/{ep.media_file}"
        items_xml.append(
            f"""    <item>
      <title>{xml_escape(ep.title)}</title>
      <description>{xml_escape(ep.description)}</description>
      <itunes:summary>{xml_escape(ep.description)}</itunes:summary>
      <itunes:author>{xml_escape(FEED_AUTHOR)}</itunes:author>
      <itunes:duration>{format_duration(ep.duration_seconds)}</itunes:duration>
      <itunes:explicit>false</itunes:explicit>
      <itunes:image href="{xml_escape(ep.thumbnail)}"/>
      <link>{xml_escape(ep.youtube_url)}</link>
      <guid isPermaLink="false">{xml_escape(ep.youtube_id)}</guid>
      <pubDate>{xml_escape(ep.published)}</pubDate>
      <enclosure url="{xml_escape(enclosure)}" length="{ep.media_bytes}" type="audio/mpeg"/>
    </item>"""
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
  xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
  xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{xml_escape(FEED_TITLE)}</title>
    <link>{xml_escape(YOUTUBE_PLAYLIST_URL)}</link>
    <description>{xml_escape(FEED_DESCRIPTION)}</description>
    <language>{xml_escape(FEED_LANGUAGE)}</language>
    <copyright>{xml_escape(FEED_COPYRIGHT)}</copyright>
    <lastBuildDate>{last_build}</lastBuildDate>
    <atom:link href="{xml_escape(self_url)}" rel="self" type="application/rss+xml"/>
    <itunes:author>{xml_escape(FEED_AUTHOR)}</itunes:author>
    <itunes:summary>{xml_escape(FEED_DESCRIPTION)}</itunes:summary>
    <itunes:explicit>false</itunes:explicit>
    <itunes:category text="{xml_escape(FEED_CATEGORY)}"/>
    <itunes:owner>
      <itunes:name>{xml_escape(FEED_AUTHOR)}</itunes:name>
      <itunes:email>{xml_escape(FEED_EMAIL)}</itunes:email>
    </itunes:owner>
    <image>
      <url>{xml_escape(cover)}</url>
      <title>{xml_escape(FEED_TITLE)}</title>
      <link>{xml_escape(YOUTUBE_PLAYLIST_URL)}</link>
    </image>
    <itunes:image href="{xml_escape(cover)}"/>
{chr(10).join(items_xml)}
  </channel>
</rss>
"""


def write_state(episodes: list[Episode]) -> None:
    STATE_PATH.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(tz=timezone.utc).isoformat(),
                "episode_count": len(episodes),
                "episodes": [asdict(ep) for ep in episodes],
            },
            indent=2,
        )
        + "\n"
    )


def render_index_html(episodes: list[Episode], base_url: str) -> str:
    base = base_url.rstrip("/")
    rss = f"{base}/rss.xml"
    host = urllib.parse.urlparse(base).netloc
    pktc = f"pktc://subscribe/{host}/rss.xml"
    web = f"https://pocketcasts.com/follow/{rss}"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Poll Position → Pocket Casts</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem;line-height:1.45}}
a.btn{{display:inline-block;margin:.4rem .4rem .4rem 0;padding:.75rem 1rem;background:#1a73e8;color:#fff;text-decoration:none;border-radius:8px;font-weight:600}}
a.btn.secondary{{background:#222}}
input{{width:100%;padding:.7rem;font-size:1rem;margin:.5rem 0 1rem;box-sizing:border-box}}
</style></head><body>
<h1>Poll Position (The Star)</h1>
<p>{len(episodes)} episodes ready.</p>
<p>
  <a class="btn" href="{escape(pktc)}">Open in Pocket Casts app</a>
  <a class="btn secondary" href="{escape(web)}">Open in Pocket Casts Web</a>
</p>
<label>Or paste this into Discover, then tap <b>Search</b> on the keyboard:</label>
<input readonly value="{escape(rss)}"/>
<p><a href="{escape(rss)}">View raw RSS</a></p>
</body></html>
"""


def run_sync(base_url: str | None = None) -> list[Episode]:
    base = (base_url or PUBLIC_BASE_URL).rstrip("/")
    episodes = sync_episodes()
    FEED_PATH.write_text(render_rss(episodes, base))
    write_state(episodes)
    (DATA_DIR / "index.html").write_text(render_index_html(episodes, base))
    print(f"Wrote {len(episodes)} episodes → {FEED_PATH}")
    return episodes


def main() -> None:
    run_sync()


if __name__ == "__main__":
    main()
