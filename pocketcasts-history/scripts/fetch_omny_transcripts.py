#!/usr/bin/env python3
"""Fetch podcast:transcript SRT files from Omny-hosted shows into notes.json."""

from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "tables"
UA = "rss-feeds-listening-log/1.0 (+https://github.com/wlad-c/rss-feeds)"
MAX_CHARS = 900

# Exact Pocket Casts show name → iTunes search term (when different)
SHOWS = [
    "The Morning Edition",
    "7am",
]


def normalize(s: str) -> str:
    s = html.unescape(s or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read()


def itunes_feed(name: str) -> str | None:
    q = urllib.parse.urlencode({"term": name, "media": "podcast", "limit": 5})
    data = json.loads(http_get(f"https://itunes.apple.com/search?{q}").decode())
    name_l = name.lower()
    for r in data.get("results") or []:
        cn = (r.get("collectionName") or "").lower()
        if (cn == name_l or name_l in cn or cn in name_l) and r.get("feedUrl"):
            return r["feedUrl"]
    if data.get("results") and data["results"][0].get("feedUrl"):
        return data["results"][0]["feedUrl"]
    return None


def srt_to_text(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.isdigit() or "-->" in line:
            continue
        # drop "Speaker N:" prefixes for denser search text
        line = re.sub(r"^Speaker\s+\d+\s*:\s*", "", line, flags=re.I)
        lines.append(line)
    text = " ".join(lines)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_CHARS]


def parse_items(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        xml_text = re.sub(r"&(?!amp;|lt;|gt;|apos;|quot;)", "&amp;", xml_text)
        root = ET.fromstring(xml_text)
    out = []
    for elem in root.iter():
        if local(elem.tag) != "item":
            continue
        title = ""
        link = ""
        tx_url = ""
        for ch in list(elem):
            ln = local(ch.tag)
            if ln == "title" and ch.text:
                title = ch.text.strip()
            elif ln == "link" and (ch.text or ch.get("href")):
                link = (ch.text or ch.get("href") or "").strip()
            elif ln == "transcript":
                u = ch.get("url") or ""
                t = (ch.get("type") or "").lower()
                if u and ("srt" in t or "subrip" in t or "format=SubRip" in u or u.endswith(".srt")):
                    tx_url = u
                elif u and not tx_url:
                    tx_url = u
        if title and tx_url:
            out.append({"title": title, "norm": normalize(title), "tx": tx_url, "link": link})
    return out


def main() -> None:
    episodes = json.loads((TABLES / "episodes.json").read_text(encoding="utf-8"))
    notes_path = TABLES / "notes.json"
    notes = json.loads(notes_path.read_text(encoding="utf-8")) if notes_path.exists() else {}

    by_show: dict[str, dict[str, int]] = {}
    for i, e in enumerate(episodes):
        p = e.get("p") or ""
        n = normalize(e.get("e") or "")
        if p and n:
            by_show.setdefault(p, {})[n] = i

    stats = {"shows": {}, "notesTotal": 0, "transcriptCount": 0}

    for show in SHOWS:
        print(f"== {show}", flush=True)
        listened = by_show.get(show) or {}
        feed = itunes_feed(show)
        time.sleep(0.2)
        if not feed:
            print("  no feed", flush=True)
            stats["shows"][show] = {"error": "no feed"}
            continue
        xml_text = http_get(feed).decode("utf-8", errors="replace")
        items = parse_items(xml_text)
        print(f"  feed txs={len(items)} listened={len(listened)}", flush=True)

        upgraded = 0
        fetched = 0
        for item in items:
            idx = listened.get(item["norm"])
            if idx is None:
                for ln, i in listened.items():
                    if len(item["norm"]) >= 28 and (item["norm"] in ln or ln in item["norm"]):
                        idx = i
                        break
            if idx is None:
                continue
            key = str(idx)
            existing = notes.get(key)
            if existing and existing.get("src") == "transcript" and len(existing.get("text") or "") > 400:
                continue
            try:
                raw = http_get(item["tx"]).decode("utf-8", errors="replace")
                time.sleep(0.08)
                text = srt_to_text(raw)
                fetched += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  fail {item['title'][:50]}: {exc}", flush=True)
                continue
            if len(text) < 120:
                continue
            notes[key] = {
                "src": "transcript",
                "text": text,
                "url": item["tx"],
                "p": show,
                "e": episodes[idx].get("e"),
            }
            upgraded += 1
            if upgraded % 40 == 0:
                print(f"  upgraded={upgraded}", flush=True)

        stats["shows"][show] = {
            "feed": feed,
            "feedTranscripts": len(items),
            "fetched": fetched,
            "upgraded": upgraded,
        }
        print(f"  done upgraded={upgraded} fetched={fetched}", flush=True)

    notes_path.write_text(
        json.dumps(notes, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    stats["notesTotal"] = len(notes)
    stats["transcriptCount"] = sum(1 for v in notes.values() if v.get("src") == "transcript")
    # merge with prior meta if present
    meta_path = TABLES / "notes-meta.json"
    prev = {}
    if meta_path.exists():
        try:
            prev = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = {}
    prev.update(stats)
    meta_path.write_text(json.dumps(prev, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2), flush=True)


if __name__ == "__main__":
    main()
