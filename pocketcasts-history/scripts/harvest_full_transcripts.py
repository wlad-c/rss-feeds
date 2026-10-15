#!/usr/bin/env python3
"""Harvest publisher transcripts + show notes into the full transcript store.

- Resolves RSS for top podcasts
- Fetches ALL podcast:transcript / transcript enclosures (no per-show budget)
- Stores FULL text in transcripts/full.sqlite (no char cap)
- Rebuilds slim notes.json snippets for Pages

Also re-pulls NPR Up First (text.npr.org) and known Omny shows.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from transcript_store import TABLES, connect, upsert_full, write_slim_notes

UA = "rss-feeds-listening-log/1.1 (+https://github.com/wlad-c/rss-feeds)"
TOP_PODCASTS = 45
REQUEST_TIMEOUT = 25

NPR_UP_FIRST_FEED = "https://feeds.npr.org/510318/podcast.xml"
OMNY_SHOW_HINTS = {
    "The Morning Edition": "The Morning Edition",
    "7am": "7am",
}


def normalize(s: str) -> str:
    s = html.unescape(s or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def http_get(url: str, accept: str = "*/*") -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": accept}, method="GET"
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return resp.read()


def http_get_text(url: str, accept: str = "*/*") -> str:
    data = http_get(url, accept=accept)
    for enc in ("utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def strip_html(raw: str) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def itunes_feed_url(name: str) -> str | None:
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


def srt_vtt_to_text(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.isdigit() or "-->" in line or line.startswith("WEBVTT"):
            continue
        if line.startswith("NOTE ") or line == "NOTE":
            continue
        line = re.sub(r"^Speaker\s+\d+\s*:\s*", "", line, flags=re.I)
        line = re.sub(r"<[^>]+>", "", line)
        lines.append(line)
    text = " ".join(lines)
    return re.sub(r"\s+", " ", text).strip()


def fetch_transcript_text(url: str, ttype: str | None = None) -> str:
    raw = http_get_text(url)
    kind = (ttype or "").lower()
    path = url.lower()
    if "json" in kind or path.endswith(".json"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                if "segments" in data:
                    return " ".join(
                        (s.get("text") or s.get("body") or "")
                        for s in data["segments"]
                    ).strip()
                if "text" in data:
                    return str(data["text"]).strip()
            if isinstance(data, list):
                return " ".join(
                    str(x.get("text") or x.get("body") or "")
                    for x in data
                    if isinstance(x, dict)
                ).strip()
        except json.JSONDecodeError:
            pass
    if "srt" in kind or "vtt" in kind or path.endswith((".srt", ".vtt")):
        return srt_vtt_to_text(raw)
    if "<" in raw[:200]:
        return strip_html(raw)
    return re.sub(r"\s+", " ", raw).strip()


def parse_rss_items(xml_text: str) -> list[dict]:
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
        desc = ""
        link = ""
        audio = ""
        transcripts: list[tuple[str, str]] = []
        for child in list(elem):
            tag = local(child.tag)
            if tag == "title":
                title = (child.text or "").strip()
            elif tag in ("description", "summary", "encoded"):
                desc = (child.text or desc or "").strip()
            elif tag == "link" and child.text:
                link = child.text.strip()
            elif tag == "enclosure":
                url = child.attrib.get("url") or ""
                typ = child.attrib.get("type") or ""
                if "audio" in typ or url.endswith((".mp3", ".m4a")):
                    audio = url
            elif tag == "transcript":
                url = child.attrib.get("url") or (child.text or "").strip()
                typ = child.attrib.get("type") or child.attrib.get("rel") or ""
                if url:
                    transcripts.append((url, typ))
        # podcast:transcript often namespaced
        for child in elem.iter():
            if local(child.tag) == "transcript":
                url = child.attrib.get("url") or (child.text or "").strip()
                typ = child.attrib.get("type") or ""
                if url and (url, typ) not in transcripts:
                    transcripts.append((url, typ))
        if title:
            out.append(
                {
                    "title": title,
                    "norm": normalize(title),
                    "desc": strip_html(desc),
                    "link": link,
                    "audio": audio,
                    "transcripts": transcripts,
                }
            )
    return out


def match_idxs(item_norm: str, listened: dict[str, list[int]]) -> list[int]:
    if item_norm in listened:
        return listened[item_norm]
    if len(item_norm) >= 28:
        for ln, idxs in listened.items():
            if item_norm in ln or ln in item_norm:
                return idxs
    return []


def story_id_from_link(link: str) -> str | None:
    m = re.search(r"/(nx-s1-\d+|g-s1-\d+)(?:/|$)", link or "")
    return m.group(1) if m else None


def extract_text_npr(story_id: str) -> str:
    raw = http_get_text(f"https://text.npr.org/{story_id}")
    paras = re.findall(r"(?is)<p[^>]*>(.*?)</p>", raw)
    parts = []
    for p in paras:
        t = re.sub(r"<[^>]+>", "", p)
        t = html.unescape(re.sub(r"\s+", " ", t)).strip()
        if not t or t.startswith("Text-Only Version") or t.startswith("NPR >"):
            continue
        parts.append(t)
    return "\n".join(parts).strip()


def harvest_show(
    conn,
    name: str,
    episodes: list[dict],
    listened: dict[str, list[int]],
    stats: dict,
) -> None:
    feed = itunes_feed_url(name)
    time.sleep(0.2)
    if not feed:
        stats["errors"].append(f"no feed: {name}")
        print("  no feed", flush=True)
        return
    stats["feedsResolved"] += 1
    xml_text = http_get_text(
        feed, accept="application/rss+xml, application/xml, text/xml, */*"
    )
    time.sleep(0.1)
    items = parse_rss_items(xml_text)
    feed_tx = sum(1 for it in items if it["transcripts"])
    print(f"  feed items={len(items)} with_transcript_tag={feed_tx}", flush=True)

    matched = 0
    for item in items:
        idxs = match_idxs(item["norm"], listened)
        if not idxs:
            continue
        text = ""
        src = "show-notes"
        url = item.get("link") or ""
        if item["transcripts"]:
            for turl, ttype in item["transcripts"]:
                try:
                    tx = fetch_transcript_text(turl, ttype)
                    time.sleep(0.08)
                except Exception as exc:  # noqa: BLE001
                    stats["errors"].append(f"{name} transcript {turl}: {exc}")
                    continue
                if tx and len(tx) > 80:
                    text = tx
                    src = "transcript"
                    url = turl
                    stats["withTranscript"] += 1
                    break
        if not text and item.get("desc"):
            text = item["desc"]
            src = "show-notes"
            stats["withDescription"] += 1
        if not text:
            continue
        for idx in idxs:
            upsert_full(
                conn,
                idx,
                text,
                src=src,
                podcast=name,
                episode=episodes[idx].get("e"),
                url=url or None,
            )
            matched += 1
    conn.commit()
    print(f"  upserted_rows≈{matched}", flush=True)
    stats["episodesMatched"] += matched


def harvest_npr_up_first(conn, episodes: list[dict], listened: dict[str, list[int]], stats: dict) -> None:
    print("[NPR] Up First text.npr.org", flush=True)
    try:
        items_xml = http_get_text(NPR_UP_FIRST_FEED)
        root = ET.fromstring(items_xml)
    except Exception as exc:  # noqa: BLE001
        stats["errors"].append(f"NPR feed: {exc}")
        return
    n = 0
    for elem in root.iter("item"):
        title = (elem.findtext("title") or "").strip()
        link = (elem.findtext("link") or "").strip()
        sid = story_id_from_link(link)
        if not title or not sid:
            continue
        idxs = match_idxs(normalize(title), listened)
        if not idxs:
            continue
        try:
            text = extract_text_npr(sid)
            time.sleep(0.12)
        except Exception as exc:  # noqa: BLE001
            stats["errors"].append(f"NPR {sid}: {exc}")
            continue
        if len(text) < 80:
            continue
        for idx in idxs:
            upsert_full(
                conn,
                idx,
                text,
                src="transcript",
                podcast="Up First from NPR",
                episode=episodes[idx].get("e"),
                url=f"https://www.npr.org/transcripts/{sid}",
            )
            n += 1
    conn.commit()
    stats["nprUpFirst"] = n
    print(f"  NPR upserted≈{n}", flush=True)


def main() -> None:
    episodes = json.loads((TABLES / "episodes.json").read_text(encoding="utf-8"))
    podcasts = json.loads((TABLES / "podcasts.json").read_text(encoding="utf-8"))
    by_show_norm: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for i, ep in enumerate(episodes):
        name = ep.get("p") or ""
        norm = normalize(ep.get("e") or "")
        if name and norm:
            by_show_norm[name][norm].append(i)

    top = sorted(podcasts, key=lambda p: p.get("n", 0), reverse=True)[:TOP_PODCASTS]
    conn = connect()
    stats: dict = {
        "podcastsTried": 0,
        "feedsResolved": 0,
        "episodesMatched": 0,
        "withDescription": 0,
        "withTranscript": 0,
        "errors": [],
    }

    # Prefer NPR upgrade for Up First before generic RSS (full text.npr.org body)
    if "Up First from NPR" in by_show_norm:
        harvest_npr_up_first(conn, episodes, by_show_norm["Up First from NPR"], stats)

    for i, pod in enumerate(top, 1):
        name = pod["p"]
        stats["podcastsTried"] += 1
        print(f"[{i}/{len(top)}] {name}", flush=True)
        listened = by_show_norm.get(name) or {}
        if not listened:
            continue
        try:
            harvest_show(conn, name, episodes, listened, stats)
        except Exception as exc:  # noqa: BLE001
            msg = f"{name}: {exc}"
            print(f"  ERROR {msg}", flush=True)
            stats["errors"].append(msg)

    meta = write_slim_notes(
        conn,
        TABLES / "notes.json",
        TABLES / "notes-meta.json",
        len(episodes),
    )
    (TABLES / "notes-meta.json").write_text(
        json.dumps({**meta, "harvest": stats}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "coverage": {
                    k: meta[k]
                    for k in (
                        "withAnyText",
                        "withPublisherOrSttTranscript",
                        "withLongText2000plus",
                        "pctTranscript",
                        "pctLongText",
                    )
                },
                "harvest": {
                    k: stats[k]
                    for k in (
                        "podcastsTried",
                        "feedsResolved",
                        "withTranscript",
                        "withDescription",
                    )
                },
                "errors": len(stats["errors"]),
            },
            indent=2,
        )
    )
    conn.close()


if __name__ == "__main__":
    main()
