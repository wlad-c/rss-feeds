#!/usr/bin/env python3
"""Upgrade notes.json with publisher-hosted transcripts where available.

Currently targets NPR Up First via text.npr.org (plain HTML transcripts).
Matches listened episodes to the public RSS feed by normalized title.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "tables"
UA = "rss-feeds-listening-log/1.0 (+https://github.com/wlad-c/rss-feeds)"
# Keep snippets searchable without blowing past GitHub Pages size limits.
MAX_CHARS = 2500
FEED = "https://feeds.npr.org/510318/podcast.xml"
SHOW = "Up First from NPR"


def normalize(s: str) -> str:
    s = html.unescape(s or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def story_id_from_link(link: str) -> str | None:
    m = re.search(r"/(nx-s1-\d+|g-s1-\d+)(?:/|$)", link or "")
    return m.group(1) if m else None


def parse_feed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for elem in root.iter("item"):
        title = (elem.findtext("title") or "").strip()
        link = (elem.findtext("link") or "").strip()
        sid = story_id_from_link(link)
        if title and sid:
            items.append({"title": title, "norm": normalize(title), "id": sid, "link": link})
    return items


def extract_text_npr(story_id: str) -> str:
    raw = http_get(f"https://text.npr.org/{story_id}").decode("utf-8", errors="replace")
    paras = re.findall(r"(?is)<p[^>]*>(.*?)</p>", raw)
    parts = []
    for p in paras:
        t = re.sub(r"<[^>]+>", "", p)
        t = html.unescape(re.sub(r"\s+", " ", t)).strip()
        if not t:
            continue
        # skip chrome
        if t.startswith("Text-Only Version") or t.startswith("NPR >"):
            continue
        parts.append(t)
    text = "\n".join(parts).strip()
    # Prefer body after date line if present
    return text[:MAX_CHARS]


def main() -> None:
    episodes = json.loads((TABLES / "episodes.json").read_text(encoding="utf-8"))
    notes_path = TABLES / "notes.json"
    notes = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.exists() else {}

    listened = {
        normalize(e.get("e") or ""): i
        for i, e in enumerate(episodes)
        if e.get("p") == SHOW and e.get("e")
    }
    print(f"listened {SHOW}: {len(listened)}", flush=True)

    feed_xml = http_get(FEED).decode("utf-8", errors="replace")
    items = parse_feed(feed_xml)
    print(f"feed items with story id: {len(items)}", flush=True)

    upgraded = 0
    fetched = 0
    skipped = 0
    for item in items:
        idx = listened.get(item["norm"])
        if idx is None:
            # soft containment
            for ln, i in listened.items():
                if len(item["norm"]) >= 28 and (item["norm"] in ln or ln in item["norm"]):
                    idx = i
                    break
        if idx is None:
            continue

        key = str(idx)
        existing = notes.get(key)
        if existing and existing.get("src") == "transcript" and len(existing.get("text") or "") > 500:
            skipped += 1
            continue

        try:
            text = extract_text_npr(item["id"])
            time.sleep(0.12)
        except Exception as exc:  # noqa: BLE001
            print(f"  fail {item['id']}: {exc}", flush=True)
            continue
        fetched += 1
        if len(text) < 200:
            print(f"  short {item['id']} ({len(text)})", flush=True)
            continue

        notes[key] = {
            "src": "transcript",
            "text": text,
            "url": f"https://www.npr.org/transcripts/{item['id']}",
            "p": SHOW,
            "e": episodes[idx].get("e"),
        }
        upgraded += 1
        if upgraded % 25 == 0:
            print(f"  upgraded={upgraded} fetched={fetched}", flush=True)

    notes_path.write_text(
        json.dumps(notes, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    meta = {
        "show": SHOW,
        "feedItems": len(items),
        "fetched": fetched,
        "upgraded": upgraded,
        "skippedExistingTranscript": skipped,
        "notesTotal": len(notes),
        "transcriptCount": sum(1 for v in notes.values() if v.get("src") == "transcript"),
    }
    (TABLES / "notes-meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2), flush=True)


if __name__ == "__main__":
    main()
