#!/usr/bin/env python3
"""Mirror the official Mano a Mano Megaphone RSS for Pocket Casts.

Fixes Pocket Casts breakage from Megaphone's enclosure length=\"0\" by probing
each audio URL for Content-Length, and publishes to a lightweight `feeds`
branch so jsDelivr is not blocked by the oversized Poll Position media tree.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
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

UA = "rss-feeds/mano-a-mano (+https://github.com/wlad-c/rss-feeds; Pocket Casts mirror)"
LENGTH_CACHE_PATH = DATA_DIR / "enclosure-lengths.json"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def fetch_source_feed() -> str:
    req = urllib.request.Request(
        SOURCE_FEED_URL,
        headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def load_length_cache() -> dict[str, int]:
    if not LENGTH_CACHE_PATH.exists():
        return {}
    try:
        raw = json.loads(LENGTH_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, int] = {}
    for key, value in raw.items():
        try:
            n = int(value)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out[str(key)] = n
    return out


def save_length_cache(cache: dict[str, int]) -> None:
    ensure_dirs()
    LENGTH_CACHE_PATH.write_text(
        json.dumps(cache, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def probe_content_length(url: str) -> int:
    """Return audio Content-Length via HEAD (follow redirects), else Range GET."""
    headers = {"User-Agent": UA, "Accept": "*/*"}
    try:
        req = urllib.request.Request(url, method="HEAD", headers=headers)
        with urllib.request.urlopen(req, timeout=45) as resp:
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit() and int(cl) > 0:
                return int(cl)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
        pass

    try:
        req = urllib.request.Request(
            url, headers={**headers, "Range": "bytes=0-0"}
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            cr = resp.headers.get("Content-Range") or ""
            # bytes 0-0/314163373
            m = re.search(r"/\s*(\d+)\s*$", cr)
            if m and int(m.group(1)) > 0:
                return int(m.group(1))
            cl = resp.headers.get("Content-Length")
            if cl and cl.isdigit() and int(cl) > 1:
                return int(cl)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
        return 0
    return 0


def fill_enclosure_lengths(rss_text: str) -> tuple[str, int, int]:
    """Replace length=\"0\" with probed byte sizes. Returns (text, fixed, missing)."""
    cache = load_length_cache()
    pattern = re.compile(
        r'(<enclosure\b[^>]*\burl=["\'])([^"\']+)(["\'][^>]*\blength=["\'])([^"\']*)(["\'])',
        re.IGNORECASE,
    )
    pattern_alt = re.compile(
        r'(<enclosure\b[^>]*\blength=["\'])([^"\']*)(["\'][^>]*\burl=["\'])([^"\']+)(["\'])',
        re.IGNORECASE,
    )

    urls: list[str] = []
    for m in pattern.finditer(rss_text):
        urls.append(m.group(2))
    if not urls:
        for m in pattern_alt.finditer(rss_text):
            urls.append(m.group(4))

    need = [u for u in dict.fromkeys(urls) if cache.get(u, 0) <= 0]
    if need:
        print(f"Probing Content-Length for {len(need)} enclosures…", flush=True)
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = {pool.submit(probe_content_length, u): u for u in need}
            for fut in as_completed(futures):
                url = futures[fut]
                try:
                    size = fut.result()
                except Exception as exc:  # noqa: BLE001
                    print(f"  WARN probe failed {url}: {exc}", flush=True)
                    size = 0
                if size > 0:
                    cache[url] = size
                    print(f"  {size} ← {url}", flush=True)
                else:
                    print(f"  WARN no length for {url}", flush=True)
        save_length_cache(cache)

    fixed = 0
    missing = 0

    def repl_url_first(m: re.Match[str]) -> str:
        nonlocal fixed, missing
        url = m.group(2)
        size = cache.get(url, 0)
        if size > 0:
            fixed += 1
            return f"{m.group(1)}{url}{m.group(3)}{size}{m.group(5)}"
        missing += 1
        return m.group(0)

    def repl_length_first(m: re.Match[str]) -> str:
        nonlocal fixed, missing
        url = m.group(4)
        size = cache.get(url, 0)
        if size > 0:
            fixed += 1
            return f"{m.group(1)}{size}{m.group(3)}{url}{m.group(5)}"
        missing += 1
        return m.group(0)

    if pattern.search(rss_text):
        text = pattern.sub(repl_url_first, rss_text)
    else:
        text = pattern_alt.sub(repl_length_first, rss_text)
    return text, fixed, missing


def rewrite_feed(raw: str, public_base: str) -> tuple[str, int]:
    """Rewrite atom:self, fill enclosure lengths, keep Megaphone audio URLs."""
    base = public_base.rstrip("/")
    self_url = f"{base}/rss.xml"
    text = raw

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

    text, fixed, missing = fill_enclosure_lengths(text)
    print(f"Enclosure lengths: fixed={fixed} missing={missing}", flush=True)
    if fixed == 0:
        raise RuntimeError(
            "Could not resolve any enclosure Content-Length values — "
            "Pocket Casts will show 0-byte episodes"
        )

    episode_count = len(re.findall(r"<item\b", text, flags=re.IGNORECASE))
    return text, episode_count


def count_enclosures(rss_text: str) -> int:
    return len(re.findall(r"<enclosure\b", rss_text, flags=re.IGNORECASE))


def count_zero_lengths(rss_text: str) -> int:
    return len(
        re.findall(r'<enclosure\b[^>]*\blength=["\']0["\']', rss_text, flags=re.IGNORECASE)
    )


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
.note{{background:#fff6e5;border:1px solid #f0d59a;padding:.75rem 1rem;border-radius:8px}}
</style></head><body>
<h1>{escape(FEED_TITLE)}</h1>
<p>{escape(FEED_DESCRIPTION)}</p>
<p>Author: {escape(FEED_AUTHOR)} · {episode_count} episodes · source: <a href="{escape(SPOTIFY_SHOW_URL)}">Spotify</a></p>
<p class="note"><b>Pocket Casts tip:</b> paste the RSS URL below into <b>Discover</b>, then tap <b>Search</b> on the keyboard (not only Go/Enter).</p>
<p>
  <a class="btn" href="{escape(pktc)}">Open in Pocket Casts app</a>
  <a class="btn secondary" href="{escape(web)}">Open in Pocket Casts Web</a>
</p>
<label>Mirrored RSS (enclosure sizes fixed for Pocket Casts):</label>
<input readonly value="{escape(rss)}"/>
<label>Official Megaphone feed:</label>
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
    ensure_dirs()
    raw = fetch_source_feed()
    rss_text, episode_count = rewrite_feed(raw, base)
    enclosures = count_enclosures(rss_text)
    zeros = count_zero_lengths(rss_text)
    if episode_count == 0:
        raise RuntimeError("Source feed has zero <item> entries")
    if enclosures == 0:
        raise RuntimeError("Source feed has zero <enclosure> tags — not playable in Pocket Casts")
    if zeros:
        print(f"WARN: {zeros} enclosures still have length=0", flush=True)
    write_outputs(rss_text, episode_count, base)
    print(
        f"Mirrored {episode_count} episodes ({enclosures} enclosures, "
        f"{zeros} zero-length) from {SOURCE_FEED_URL}"
    )
    print(f"Wrote {FEED_PATH}")
    return rss_text, episode_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Mirror Mano a Mano → podcast RSS")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Also write a static site/mano-a-mano/ tree for the feeds branch",
    )
    args = parser.parse_args()
    rss_text, episode_count = run_sync(PUBLIC_BASE_URL)
    if args.publish:
        publish_site(rss_text, episode_count, PUBLIC_BASE_URL)


if __name__ == "__main__":
    main()
