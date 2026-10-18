#!/usr/bin/env python3
"""Fetch additional free publisher transcripts for high-gap shows.

Sources:
  - Foro de Teresina — revista piauí pages piaui.uol.com.br/web/ftNNN/
  - The National Security Podcast — AI transcripts on nsc.anu.edu.au/podcast/*
  - Politics with Michelle Grattan — "Full transcript" on theconversation.com

Writes full text into transcripts/full.sqlite and rebuilds slim notes.json.
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from transcript_store import TABLES, connect, upsert_full, write_slim_notes

UA = "rss-feeds-listening-log/1.3 (+https://github.com/wlad-c/rss-feeds)"
REQUEST_TIMEOUT = 30

FORO_SHOW = "Foro de Teresina"
FORO_FEED = "https://feeds.megaphone.fm/NPP2619427256"

NSC_SHOW = "The National Security Podcast"
NSC_FEED = "https://feeds.acast.com/public/shows/13de84ee-6f50-420b-9f5a-52e94d3a2597"

GRATTAN_SHOW = "Politics with Michelle Grattan"


def normalize(s: str) -> str:
    s = html.unescape(s or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def http_get_text(url: str, accept: str = "*/*") -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": accept}, method="GET"
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        data = resp.read()
    for enc in ("utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def match_idxs(item_norm: str, listened: dict[str, list[int]]) -> list[int]:
    if item_norm in listened:
        return listened[item_norm]
    if len(item_norm) >= 20:
        for ln, idxs in listened.items():
            if item_norm in ln or ln in item_norm:
                return idxs
    # token overlap fallback
    a = {t for t in item_norm.split() if len(t) >= 4}
    if len(a) < 2:
        return []
    best: tuple[float, list[int]] | None = None
    for ln, idxs in listened.items():
        b = {t for t in ln.split() if len(t) >= 4}
        if not b:
            continue
        overlap = len(a & b) / min(len(a), len(b))
        if overlap >= 0.7 and (best is None or overlap > best[0]):
            best = (overlap, idxs)
    return best[1] if best else []


def strip_tags(raw: str) -> str:
    raw = re.sub(r"(?is)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?is)</p>", "\n", raw)
    raw = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", raw)
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
        for ch in list(elem):
            ln = local(ch.tag)
            if ln == "title" and ch.text:
                title = html.unescape(ch.text.strip())
            elif ln in ("description", "summary", "encoded"):
                desc = html.unescape((ch.text or desc or "").strip())
            elif ln == "link" and (ch.text or ch.get("href")):
                link = (ch.text or ch.get("href") or "").strip()
        if title:
            out.append(
                {
                    "title": title,
                    "norm": normalize(title),
                    "desc": desc,
                    "link": link,
                }
            )
    return out


def extract_foro_transcript(page: str) -> tuple[str, str]:
    title = ""
    m = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", page)
    if m:
        title = strip_tags(m.group(1))
    tm = re.search(
        r"(?is)TRANSCRI[CÇ][AÃ]O DE [AÁ]UDIO:?\s*(.*)$",
        page,
    )
    if not tm:
        return title, ""
    chunk = tm.group(1)
    # stop before heavy footer chrome when possible
    chunk = re.split(
        r"(?is)(Leia também|Assine a piauí|newsletter|class=\"footer\")",
        chunk,
    )[0]
    text = strip_tags(chunk)
    return title, text


def harvest_foro(
    conn, episodes: list[dict], listened: dict[str, list[int]], stats: dict
) -> None:
    print(f"[Foro] {FORO_SHOW}", flush=True)
    # Prefer feed-linked ft pages; also probe a contiguous recent range.
    xml_text = http_get_text(FORO_FEED)
    time.sleep(0.1)
    items = parse_rss_items(xml_text)
    url_by_title: dict[str, str] = {}
    for it in items:
        m = re.search(r"https?://piaui\.uol\.com\.br/web/ft\d+/?", it["desc"])
        if m:
            url_by_title[it["norm"]] = m.group(0).rstrip("/") + "/"

    urls = set(url_by_title.values())
    for n in range(110, 160):
        urls.add(f"https://piaui.uol.com.br/web/ft{n}/")
    print(f"  candidate URLs: {len(urls)} (feed-linked={len(url_by_title)})", flush=True)

    upgraded = skipped = failed = matched = 0

    def fetch_one(url: str) -> tuple[str, str, str, str | None]:
        try:
            page = http_get_text(url)
            title, text = extract_foro_transcript(page)
            return url, title, text, None
        except Exception as exc:  # noqa: BLE001
            return url, "", "", str(exc)

    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(fetch_one, u) for u in sorted(urls)]
        for i, fut in enumerate(as_completed(futs), 1):
            url, title, text, err = fut.result()
            if err:
                failed += 1
                continue
            if len(text) < 500:
                continue
            idxs = match_idxs(normalize(title), listened) if title else []
            if not idxs:
                # try reverse: any feed title pointing at this URL
                for tnorm, u in url_by_title.items():
                    if u.rstrip("/") == url.rstrip("/"):
                        idxs = match_idxs(tnorm, listened)
                        if idxs:
                            title = episodes[idxs[0]].get("e") or title
                        break
            if not idxs:
                continue
            matched += 1
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
                    podcast=FORO_SHOW,
                    episode=episodes[idx].get("e"),
                    url=url,
                )
                upgraded += 1
            if upgraded % 10 == 0:
                conn.commit()
            if i % 20 == 0:
                print(
                    f"  scanned={i}/{len(urls)} upgraded≈{upgraded} matched={matched}",
                    flush=True,
                )
    conn.commit()
    stats["foro"] = {
        "candidates": len(urls),
        "matched": matched,
        "upgraded": upgraded,
        "skipped": skipped,
        "failed": failed,
    }
    print(
        f"  done upgraded≈{upgraded} matched={matched} skipped={skipped} failed={failed}",
        flush=True,
    )


def extract_nsc_transcript(page: str) -> str:
    # Prefer block after AI-generated disclaimer
    m = re.search(
        r"(?is)\(This transcript is AI-generated[^)]*\)\s*(.*?)(?:Hosted on Acast|We.?d love to hear|Follow us on|Be sure to subscribe|$)",
        page,
    )
    if not m:
        m = re.search(
            r"(?is)<h2[^>]*>\s*Transcript\s*</h2>\s*(.*?)(?:Hosted on Acast|We.?d love to hear|$)",
            page,
        )
    if not m:
        return ""
    return strip_tags(m.group(1))


def harvest_nsc(
    conn, episodes: list[dict], listened: dict[str, list[int]], stats: dict
) -> None:
    print(f"[NSC] {NSC_SHOW}", flush=True)
    xml_text = http_get_text(NSC_FEED)
    time.sleep(0.1)
    items = parse_rss_items(xml_text)
    pairs: list[tuple[str, str]] = []  # title, clean nsc url
    seen = set()
    for it in items:
        blob = f"{it['desc']} {it['link']}"
        urls = re.findall(r"https?://nsc\.anu\.edu\.au/podcast/[a-z0-9-]+", blob)
        if not urls:
            continue
        url = urls[0].split("#")[0]
        if url in seen:
            continue
        seen.add(url)
        pairs.append((it["title"], url))
    print(f"  feed items with NSC pages: {len(pairs)}", flush=True)

    upgraded = skipped = failed = matched = 0

    def fetch_one(title: str, url: str) -> tuple[str, str, str, str | None]:
        try:
            page = http_get_text(url)
            text = extract_nsc_transcript(page)
            return title, url, text, None
        except Exception as exc:  # noqa: BLE001
            return title, url, "", str(exc)

    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(fetch_one, t, u) for t, u in pairs]
        for i, fut in enumerate(as_completed(futs), 1):
            title, url, text, err = fut.result()
            if err:
                failed += 1
                if failed <= 6:
                    stats["errors"].append(f"NSC {url}: {err}")
                continue
            idxs = match_idxs(normalize(title), listened)
            if not idxs:
                continue
            matched += 1
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
                    podcast=NSC_SHOW,
                    episode=episodes[idx].get("e"),
                    url=url,
                )
                upgraded += 1
            if upgraded % 10 == 0:
                conn.commit()
            if i % 15 == 0:
                print(
                    f"  scanned={i}/{len(pairs)} upgraded≈{upgraded} matched={matched}",
                    flush=True,
                )
    conn.commit()
    stats["nsc"] = {
        "candidates": len(pairs),
        "matched": matched,
        "upgraded": upgraded,
        "skipped": skipped,
        "failed": failed,
    }
    print(
        f"  done upgraded≈{upgraded} matched={matched} skipped={skipped} failed={failed}",
        flush=True,
    )


def extract_grattan_transcript(page: str) -> str:
    m = re.search(
        r"(?is)Full transcript(?:\s*\([^)]*\))?\s*</h[12]>\s*(.*?)(?:Content from|Authors|Related Topics|<aside|Subscribe|$)",
        page,
    )
    if not m:
        return ""
    return strip_tags(m.group(1))


def conversation_search(title: str) -> list[str]:
    q = urllib.parse.quote(f"Politics with Michelle Grattan {title}")
    page = http_get_text(f"https://theconversation.com/au/search?q={q}")
    rel = re.findall(r'href="(/politics-with-michelle-grattan-[^"#?]+)"', page)
    out = []
    seen = set()
    for r in rel:
        if r in seen:
            continue
        seen.add(r)
        out.append("https://theconversation.com" + r)
    return out


def harvest_grattan(
    conn, episodes: list[dict], listened: dict[str, list[int]], stats: dict
) -> None:
    print(f"[Grattan] {GRATTAN_SHOW}", flush=True)
    # Unique listened titles
    targets: list[tuple[list[int], str]] = []
    for norm, idxs in listened.items():
        title = episodes[idxs[0]].get("e") or norm
        targets.append((idxs, title))
    print(f"  listened titles: {len(targets)}", flush=True)

    upgraded = skipped = failed = matched = no_tx = 0
    for i, (idxs, title) in enumerate(targets, 1):
        try:
            candidates = conversation_search(title)
            time.sleep(0.2)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            if failed <= 6:
                stats["errors"].append(f"Grattan search {title}: {exc}")
            continue
        text = ""
        url = ""
        for cand in candidates[:3]:
            try:
                page = http_get_text(cand)
                time.sleep(0.15)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                continue
            tx = extract_grattan_transcript(page)
            if len(tx) >= 400:
                text = tx
                url = cand
                break
        if not text:
            no_tx += 1
            if i % 10 == 0:
                print(
                    f"  scanned={i}/{len(targets)} upgraded≈{upgraded} no_tx={no_tx}",
                    flush=True,
                )
            continue
        matched += 1
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
                podcast=GRATTAN_SHOW,
                episode=episodes[idx].get("e"),
                url=url,
            )
            upgraded += 1
        conn.commit()
        print(f"  + {title[:60]!r} ({len(text)} chars)", flush=True)
    stats["grattan"] = {
        "targets": len(targets),
        "matchedWithTranscript": matched,
        "upgraded": upgraded,
        "skipped": skipped,
        "noTranscriptOnPage": no_tx,
        "failed": failed,
    }
    print(
        f"  done upgraded≈{upgraded} matched={matched} no_tx={no_tx} skipped={skipped}",
        flush=True,
    )


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

    if FORO_SHOW in by_show:
        harvest_foro(conn, episodes, by_show[FORO_SHOW], stats)
    if NSC_SHOW in by_show:
        harvest_nsc(conn, episodes, by_show[NSC_SHOW], stats)
    if GRATTAN_SHOW in by_show:
        harvest_grattan(conn, episodes, by_show[GRATTAN_SHOW], stats)

    meta = write_slim_notes(
        conn,
        TABLES / "notes.json",
        TABLES / "notes-meta.json",
        len(episodes),
    )
    (TABLES / "notes-meta.json").write_text(
        json.dumps(
            {**meta, "morePublisherHarvest": stats}, ensure_ascii=False, indent=2
        ),
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
                        "pctTranscript",
                        "bySrc",
                    )
                },
                "morePublisherHarvest": {
                    k: stats.get(k) for k in ("foro", "nsc", "grattan")
                },
                "errors": len(stats["errors"]),
            },
            indent=2,
        ),
        flush=True,
    )
    conn.close()


if __name__ == "__main__":
    main()
