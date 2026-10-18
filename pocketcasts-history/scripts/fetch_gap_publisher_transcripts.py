#!/usr/bin/env python3
"""Fetch publisher-hosted transcripts for high-gap shows.

Sources:
  - ABC News Daily — full transcript on abc.net.au/listen episode pages
  - Durma com essa (Nexo) — "Transcrição do episódio" in nexojornal.com.br story JSON
  - Morning Brief (BFM) — rare podcast:transcript SRT tags on Omny RSS

Writes full text into transcripts/full.sqlite and rebuilds slim notes.json.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

from transcript_store import TABLES, connect, upsert_full, write_slim_notes

UA = "rss-feeds-listening-log/1.2 (+https://github.com/wlad-c/rss-feeds)"
REQUEST_TIMEOUT = 30

ABC_NEWS_DAILY_FEED = "https://www.abc.net.au/feeds/9443166/podcast.xml"
ABC_SHOW = "ABC News Daily"

NEXO_SHOW = "Durma com essa"
NEXO_SITEMAP_INDEX = "https://www.nexojornal.com.br/sitemap.xml"

BFM_SHOW = "Morning Brief"
BFM_FEED = (
    "https://www.omnycontent.com/d/playlist/"
    "de62ff84-6498-49d0-a266-a9d50120c712/"
    "348bcb36-1085-4351-a720-ab0900403779/"
    "962d774e-ec4d-4ac7-89ad-ab090040377e/podcast.rss"
)


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


def match_idxs(item_norm: str, listened: dict[str, list[int]]) -> list[int]:
    if item_norm in listened:
        return listened[item_norm]
    if len(item_norm) >= 24:
        for ln, idxs in listened.items():
            if item_norm in ln or ln in item_norm:
                return idxs
    return []


def srt_to_text(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.isdigit() or "-->" in line:
            continue
        line = re.sub(r"^Speaker\s+\d+\s*:\s*", "", line, flags=re.I)
        lines.append(line)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def extract_abc_listen_transcript(page: str) -> str:
    m = re.search(
        r'(?is)<div id="transcript"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        page,
    )
    if not m:
        m = re.search(r'(?is)<div id="transcript"[^>]*>(.*)$', page)
    if not m:
        return ""
    chunk = m.group(1)
    chunk = re.sub(r"(?is)</p>", "\n", chunk)
    chunk = re.sub(r"(?is)<br\s*/?>", "\n", chunk)
    text = re.sub(r"<[^>]+>", " ", chunk)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def harvest_abc_news_daily(
    conn, episodes: list[dict], listened: dict[str, list[int]], stats: dict
) -> None:
    print(f"[ABC] {ABC_SHOW}", flush=True)
    xml_text = http_get_text(
        ABC_NEWS_DAILY_FEED,
        accept="application/rss+xml, application/xml, text/xml, */*",
    )
    time.sleep(0.15)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        xml_text = re.sub(r"&(?!amp;|lt;|gt;|apos;|quot;)", "&amp;", xml_text)
        root = ET.fromstring(xml_text)

    items = []
    for elem in root.iter("item"):
        title = (elem.findtext("title") or "").strip()
        link = (elem.findtext("link") or "").strip()
        if title and link and "abc.net.au/listen/" in link:
            items.append({"title": title, "norm": normalize(title), "link": link})
    print(f"  feed items with listen links: {len(items)}", flush=True)

    upgraded = 0
    skipped = 0
    failed = 0
    for item in items:
        idxs = match_idxs(item["norm"], listened)
        if not idxs:
            continue
        # Skip if we already have a long publisher transcript
        existing = conn.execute(
            "SELECT src, chars FROM transcripts WHERE episode_idx=?",
            (idxs[0],),
        ).fetchone()
        if (
            existing
            and existing[0] == "transcript"
            and int(existing[1] or 0) >= 2000
        ):
            skipped += 1
            continue
        try:
            page = http_get_text(item["link"])
            time.sleep(0.18)
            text = extract_abc_listen_transcript(page)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            stats["errors"].append(f"ABC {item['link']}: {exc}")
            continue
        if len(text) < 200:
            failed += 1
            continue
        for idx in idxs:
            upsert_full(
                conn,
                idx,
                text,
                src="transcript",
                podcast=ABC_SHOW,
                episode=episodes[idx].get("e"),
                url=item["link"],
            )
            upgraded += 1
        if upgraded % 25 == 0:
            conn.commit()
            print(f"  upgraded≈{upgraded}", flush=True)
    conn.commit()
    stats["abcNewsDaily"] = {
        "feedItems": len(items),
        "upgraded": upgraded,
        "skippedExisting": skipped,
        "failed": failed,
    }
    print(f"  done upgraded≈{upgraded} skipped={skipped} failed={failed}", flush=True)


def nexo_podcast_urls() -> list[str]:
    index = http_get_text(NEXO_SITEMAP_INDEX)
    time.sleep(0.1)
    locs = re.findall(r"<loc>(.*?)</loc>", index)
    urls: list[str] = []
    for loc in locs:
        if "story-sitemap" not in loc:
            continue
        try:
            body = http_get_text(loc)
            time.sleep(0.08)
        except Exception:  # noqa: BLE001
            continue
        for u in re.findall(r"<loc>(https://www\.nexojornal\.com\.br/podcast/\d{4}/\d{2}/\d{2}/[^<]+)</loc>", body):
            urls.append(u.rstrip("/"))
    # newest first
    urls = sorted(set(urls), reverse=True)
    return urls


def extract_nexo_transcript(page: str) -> tuple[str, str]:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        return "", ""
    try:
        nd = json.loads(m.group(1))
        post = nd["props"]["pageProps"]["post"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return "", ""
    title = (post.get("title") or "").strip()
    content = post.get("content") or ""
    # Heading may be plain or wrapped in <strong>, e.g.
    # <h2>Transcrição…</h2> or <h2><strong>Transcrição…</strong></h2>
    tm = re.search(
        r"(?is)<h2[^>]*>\s*(?:<strong>)?\s*Transcri[cç][aã]o do epis[oó]dio\s*"
        r"(?:</strong>)?\s*</h2>\s*(.*)$",
        content,
    )
    if not tm:
        tm = re.search(
            r"(?is)Transcri[cç][aã]o do epis[oó]dio\s*(?:</strong>)?\s*</h2>\s*(.*)$",
            content,
        )
    if not tm:
        return title, ""
    chunk = tm.group(1)
    chunk = re.sub(r"(?is)<br\s*/?>", "\n", chunk)
    chunk = re.sub(r"(?is)</p>", "\n", chunk)
    text = re.sub(r"<[^>]+>", " ", chunk)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return title, text


def _url_date(url: str) -> str | None:
    m = re.search(r"/podcast/(\d{4}/\d{2}/\d{2})/", url)
    return m.group(1).replace("/", "-") if m else None


def harvest_nexo_durma(
    conn, episodes: list[dict], listened: dict[str, list[int]], stats: dict
) -> None:
    print(f"[Nexo] {NEXO_SHOW}", flush=True)
    # Dates (±1 day) for listened Durma episodes — sitemap URLs outside this set are skipped.
    listened_dates: set[str] = set()
    for idxs in listened.values():
        for idx in idxs:
            pub = (episodes[idx].get("pub") or "")[:10]
            if not re.match(r"\d{4}-\d{2}-\d{2}$", pub):
                continue
            d0 = date.fromisoformat(pub)
            for delta in (-1, 0, 1):
                listened_dates.add((d0 + timedelta(days=delta)).isoformat())

    urls = nexo_podcast_urls()
    candidates = [u for u in urls if (_url_date(u) or "") in listened_dates]
    print(
        f"  sitemap podcast URLs: {len(urls)}; date-matched candidates: {len(candidates)}",
        flush=True,
    )

    def fetch_one(url: str) -> tuple[str, str, str, str | None]:
        try:
            page = http_get_text(url)
            title, text = extract_nexo_transcript(page)
            return url, title, text, None
        except Exception as exc:  # noqa: BLE001
            return url, "", "", str(exc)

    upgraded = 0
    skipped = 0
    failed = 0
    matched_pages = 0
    done = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch_one, u) for u in candidates]
        for fut in as_completed(futures):
            url, title, text, err = fut.result()
            done += 1
            if err:
                failed += 1
                if failed <= 8:
                    stats["errors"].append(f"Nexo {url}: {err}")
                continue
            if not title:
                continue
            idxs = match_idxs(normalize(title), listened)
            if not idxs:
                continue
            matched_pages += 1
            if len(text) < 400:
                continue
            existing = conn.execute(
                "SELECT src, chars FROM transcripts WHERE episode_idx=?",
                (idxs[0],),
            ).fetchone()
            if (
                existing
                and existing[0] in ("transcript", "youtube", "stt")
                and int(existing[1] or 0) >= len(text)
            ):
                skipped += 1
                continue
            for idx in idxs:
                upsert_full(
                    conn,
                    idx,
                    text,
                    src="transcript",
                    podcast=NEXO_SHOW,
                    episode=episodes[idx].get("e"),
                    url=url,
                )
                upgraded += 1
            if upgraded and upgraded % 25 == 0:
                conn.commit()
            if done % 50 == 0 or done == len(candidates):
                print(
                    f"  scanned={done}/{len(candidates)} upgraded≈{upgraded} matched={matched_pages}",
                    flush=True,
                )
    conn.commit()
    stats["nexoDurma"] = {
        "sitemapUrls": len(urls),
        "candidates": len(candidates),
        "matchedPages": matched_pages,
        "upgraded": upgraded,
        "skippedExisting": skipped,
        "failed": failed,
    }
    print(
        f"  done upgraded≈{upgraded} matched={matched_pages} skipped={skipped} failed={failed}",
        flush=True,
    )


def harvest_bfm_morning_brief(
    conn, episodes: list[dict], listened: dict[str, list[int]], stats: dict
) -> None:
    print(f"[BFM] {BFM_SHOW} Omny podcast:transcript", flush=True)
    xml_text = http_get_text(
        BFM_FEED, accept="application/rss+xml, application/xml, text/xml, */*"
    )
    time.sleep(0.15)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        xml_text = re.sub(r"&(?!amp;|lt;|gt;|apos;|quot;)", "&amp;", xml_text)
        root = ET.fromstring(xml_text)

    upgraded = 0
    for elem in root.iter():
        if local(elem.tag) != "item":
            continue
        title = ""
        tx_url = ""
        for ch in list(elem):
            ln = local(ch.tag)
            if ln == "title" and ch.text:
                title = ch.text.strip()
            elif ln == "transcript":
                u = ch.get("url") or ""
                t = (ch.get("type") or "").lower()
                if u and ("srt" in t or "subrip" in t or "format=SubRip" in u):
                    tx_url = html.unescape(u)
        if not title or not tx_url:
            continue
        idxs = match_idxs(normalize(title), listened)
        if not idxs:
            continue
        try:
            raw = http_get_text(tx_url)
            time.sleep(0.12)
            text = srt_to_text(raw)
        except Exception as exc:  # noqa: BLE001
            stats["errors"].append(f"BFM {tx_url}: {exc}")
            continue
        if len(text) < 200:
            continue
        for idx in idxs:
            upsert_full(
                conn,
                idx,
                text,
                src="transcript",
                podcast=BFM_SHOW,
                episode=episodes[idx].get("e"),
                url=tx_url,
            )
            upgraded += 1
    conn.commit()
    stats["bfmMorningBrief"] = {"upgraded": upgraded}
    print(f"  done upgraded≈{upgraded}", flush=True)


def main() -> None:
    episodes = json.loads((TABLES / "episodes.json").read_text(encoding="utf-8"))
    by_show: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for i, ep in enumerate(episodes):
        name = ep.get("p") or ""
        norm = normalize(ep.get("e") or "")
        if name and norm:
            by_show[name][norm].append(i)

    conn = connect()
    stats: dict = {"errors": []}

    if ABC_SHOW in by_show:
        harvest_abc_news_daily(conn, episodes, by_show[ABC_SHOW], stats)
    if NEXO_SHOW in by_show:
        harvest_nexo_durma(conn, episodes, by_show[NEXO_SHOW], stats)
    if BFM_SHOW in by_show:
        harvest_bfm_morning_brief(conn, episodes, by_show[BFM_SHOW], stats)

    meta = write_slim_notes(
        conn,
        TABLES / "notes.json",
        TABLES / "notes-meta.json",
        len(episodes),
    )
    (TABLES / "notes-meta.json").write_text(
        json.dumps({**meta, "gapPublisherHarvest": stats}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    cov = {
        "coverage": {
            k: meta[k]
            for k in (
                "withAnyText",
                "withPublisherOrSttTranscript",
                "withLongText2000plus",
                "pctTranscript",
                "pctLongText",
                "bySrc",
            )
        },
        "gapPublisherHarvest": {
            k: stats.get(k)
            for k in ("abcNewsDaily", "nexoDurma", "bfmMorningBrief")
        },
        "errors": len(stats["errors"]),
    }
    print(json.dumps(cov, indent=2), flush=True)
    conn.close()


if __name__ == "__main__":
    main()
