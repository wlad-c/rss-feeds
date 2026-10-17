#!/usr/bin/env python3
"""Match listened episodes to YouTube uploads and harvest caption transcripts.

YouTube blocks most cloud/datacenter IPs for direct caption fetches
(youtube-transcript-api / yt-dlp timedtext). This script tries backends in order:

  1. youtube-transcript-api  — works on residential IPs / with WEBSHARE_* proxies
  2. YTAPI_API_KEY           — optional https://ytapi.dev key (env)
  3. transcribeyoutube.com   — free hosted extractor (no key; fair-use rate limits)

Matching prefers channel upload lists (reliable), then yt-dlp `ytsearchN:` fallback.

Stores FULL text in transcripts/full.sqlite with src=youtube.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from transcript_store import TABLES, connect, get_full, upsert_full, write_slim_notes

UA = "rss-feeds-listening-log/1.1 (+https://github.com/wlad-c/rss-feeds)"
TRANSCRIBE_YT_URL = "https://transcribeyoutube.com/api/transcript"

# podcast → YouTube channel handle / uploads URL seed
YT_CHANNELS: dict[str, dict] = {
    "The Daily": {
        "handle": "@NYTPodcasts",
        "title_must": None,  # mixed channel; rely on title score vs episode
        "reject_title": [
            "wirecutter",
            "modern love",
            "the interview",
            "hard fork",
            "book review",
            "the ezra klein",
        ],
    },
    "The Ezra Klein Show": {
        "handle": "@EzraKleinShow",
        "title_must": None,
        "reject_title": [],
    },
    "ABC News Daily": {
        "handle": "@abcnewsaustralia",
        "title_must": "abc news daily",
        "reject_title": [],
    },
    "Politics Now": {
        "handle": "@abcnewsaustralia",
        "title_must": "politics now",
        "reject_title": [],
    },
    "Up First from NPR": {
        "handle": "@nprpodcasts",
        "title_must": "up first",
        "reject_title": [],
    },
    "7am": {
        "handle": "@7ampodcast",
        "title_must": None,
        "reject_title": [],
    },
    "O Assunto": {
        "handle": "@oassunto",
        "title_must": None,
        "reject_title": [],
    },
    "Foro de Teresina": {
        "handle": "@ForodeTeresina",
        "title_must": None,
        "reject_title": [],
    },
    "Xadrez Verbal": {
        "handle": "@XadrezVerbal",
        "title_must": None,
        "reject_title": [],
    },
    "Lowy Institute": {
        "handle": "@LowyInstitute",
        "title_must": None,
        "reject_title": [],
    },
    "Sinica Podcast": {
        "handle": "@SinicaPodcast",
        "title_must": None,
        "reject_title": [],
    },
}

# Search hints when no channel list / fallback
YT_SHOW_HINTS: dict[str, str] = {
    name: conf["handle"].lstrip("@") for name, conf in YT_CHANNELS.items()
}
YT_SHOW_HINTS.update(
    {
        "The Morning Edition": "The Morning Edition podcast",
        "Democracy Sausage with Mark Kenny": "Democracy Sausage Mark Kenny",
        "Australian Politics": "Australian Politics podcast",
        "Global Roaming with Geraldine Doogue and Hamish Macdonald": "Global Roaming ABC",
        "The National Security Podcast": "National Security Podcast",
        "ASPI Podcast: Policy, Guns & Money": "ASPI Policy Guns Money",
        "Asia Geopolitics": "Asia Geopolitics podcast",
        "Australia in the World": "Australia in the World podcast",
        "Beyond the Ballot Box": "Beyond the Ballot Box",
        "CNA Correspondent": "CNA Correspondent",
        "Petit Journal": "Petit Journal podcast",
        "Durma com essa": "Durma com essa",
        "Boletim Folha": "Boletim Folha",
        "Morning Brief": "Morning Brief podcast",
    }
)

PRIORITY_SHOWS = [
    "The Daily",
    "The Ezra Klein Show",
    "ABC News Daily",
    "Politics Now",
    "Up First from NPR",
    "7am",
    "O Assunto",
    "Foro de Teresina",
    "Xadrez Verbal",
    "Lowy Institute",
    "Sinica Podcast",
    "The Morning Edition",
    "Democracy Sausage with Mark Kenny",
    "Australian Politics",
    "Global Roaming with Geraldine Doogue and Hamish Macdonald",
    "The National Security Podcast",
]


def normalize(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def token_set(s: str) -> set[str]:
    stop = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "from",
        "podcast",
        "episode",
        "ep",
        "full",
        "video",
        "news",
        "abc",
        "daily",
    }
    return {t for t in normalize(s).split() if len(t) > 1 and t not in stop}


def title_score(ep_title: str, yt_title: str) -> float:
    a, b = normalize(ep_title), normalize(yt_title)
    if not a or not b:
        return 0.0
    for prefix in (
        "the daily ",
        "up first ",
        "abc news daily ",
        "politics now ",
        "7am ",
        "the ezra klein show ",
    ):
        if b.startswith(prefix):
            b = b[len(prefix) :]
    # Drop trailing " | show name"
    if " | " in yt_title:
        b = normalize(yt_title.split(" | ", 1)[0])
    seq = SequenceMatcher(None, a, b).ratio()
    ta, tb = token_set(a), token_set(b)
    jacc = (len(ta & tb) / len(ta | tb)) if ta and tb else 0.0
    contain = 1.0 if (a in b or b in a) else 0.0
    return 0.45 * seq + 0.45 * jacc + 0.10 * contain


def parse_minutes(dur: str | None) -> float:
    if not dur:
        return 0.0
    parts = (dur or "").split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60
        if len(parts) == 2:
            return int(parts[0]) + int(parts[1]) / 60
    except ValueError:
        return 0.0
    return 0.0


def yt_dump(url_or_query: str, limit: int = 50) -> list[dict]:
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
        "--playlist-end",
        str(limit),
        url_or_query,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    out: list[dict] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            j = json.loads(line)
        except json.JSONDecodeError:
            continue
        vid = j.get("id")
        if not vid:
            continue
        out.append(
            {
                "id": vid,
                "title": j.get("title") or "",
                "uploader": j.get("uploader") or j.get("channel") or "",
                "url": j.get("url") or f"https://www.youtube.com/watch?v={vid}",
            }
        )
    return out


def yt_search(query: str, n: int = 5) -> list[dict]:
    return yt_dump(f"ytsearch{n}:{query}", limit=n)


def channel_uploads(handle: str, limit: int = 250) -> list[dict]:
    handle = handle if handle.startswith("@") else f"@{handle}"
    return yt_dump(f"https://www.youtube.com/{handle}/videos", limit=limit)


def fetch_yta(video_id: str) -> str | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api.proxies import WebshareProxyConfig
    except ImportError:
        return None

    kwargs = {}
    user = os.environ.get("WEBSHARE_PROXY_USERNAME")
    password = os.environ.get("WEBSHARE_PROXY_PASSWORD")
    if user and password:
        kwargs["proxy_config"] = WebshareProxyConfig(
            proxy_username=user, proxy_password=password
        )
    try:
        api = YouTubeTranscriptApi(**kwargs)
        fetched = api.fetch(video_id)
        parts = []
        for snip in fetched:
            text = getattr(snip, "text", None)
            if text is None and isinstance(snip, dict):
                text = snip.get("text")
            if text:
                parts.append(str(text))
        text = re.sub(r"\s+", " ", " ".join(parts)).strip()
        return text if len(text) >= 80 else None
    except Exception:  # noqa: BLE001
        return None


def fetch_ytapi(video_id: str) -> str | None:
    key = os.environ.get("YTAPI_API_KEY") or os.environ.get("YTAPI_KEY")
    if not key:
        return None
    url = f"https://ytapi.dev/api/transcript?id={urllib.parse.quote(video_id)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "application/json", "X-API-Key": key},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode())
    except Exception:  # noqa: BLE001
        return None
    if isinstance(data, dict):
        if isinstance(data.get("transcript"), str) and len(data["transcript"]) >= 80:
            return data["transcript"].strip()
        segs = data.get("transcript") or data.get("segments") or data.get("text")
        if isinstance(segs, list):
            parts = []
            for s in segs:
                if isinstance(s, str):
                    parts.append(s)
                elif isinstance(s, dict):
                    parts.append(s.get("text") or s.get("content") or "")
            text = re.sub(r"\s+", " ", " ".join(parts)).strip()
            return text if len(text) >= 80 else None
        if isinstance(segs, str) and len(segs) >= 80:
            return segs.strip()
    return None


class RateLimited(Exception):
    def __init__(self, retry_after: float | None = None):
        self.retry_after = retry_after
        super().__init__(f"rate limited retry_after={retry_after}")


def fetch_transcribe_yt(video_id: str) -> str | None:
    body = json.dumps(
        {"url": f"https://www.youtube.com/watch?v={video_id}"}
    ).encode()
    req = urllib.request.Request(
        TRANSCRIBE_YT_URL,
        data=body,
        method="POST",
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        payload = b""
        try:
            payload = exc.read()
        except Exception:  # noqa: BLE001
            pass
        if exc.code == 429:
            retry = None
            try:
                j = json.loads(payload.decode())
                retry = float(j.get("retryAfter") or j.get("retry_after") or 0) or None
            except Exception:  # noqa: BLE001
                pass
            raise RateLimited(retry)
        return None
    except Exception:  # noqa: BLE001
        return None

    if not isinstance(data, dict) or not data.get("ok", True):
        err = (data or {}).get("error") if isinstance(data, dict) else None
        if err in ("RATE_LIMITED", "rate_limited"):
            raise RateLimited()
        return None
    segs = data.get("transcript") or []
    if isinstance(segs, str):
        text = segs.strip()
    elif isinstance(segs, list):
        parts = []
        for s in segs:
            if isinstance(s, str):
                parts.append(s)
            elif isinstance(s, dict):
                parts.append(s.get("text") or "")
        text = re.sub(r"\s+", " ", " ".join(parts)).strip()
    else:
        return None
    return text if len(text) >= 80 else None


def fetch_captions(video_id: str, backends: list[str]) -> tuple[str | None, str | None]:
    for name in backends:
        if name == "yta":
            text = fetch_yta(video_id)
            if text:
                return text, "yta"
        elif name == "ytapi":
            text = fetch_ytapi(video_id)
            if text:
                return text, "ytapi"
        elif name == "transcribe_yt":
            text = fetch_transcribe_yt(video_id)
            if text:
                return text, "transcribe_yt"
    return None, None


def needs_youtube(
    conn, idx: int, episodes: list[dict], min_chars: int = 2000
) -> bool:
    ep = episodes[idx] if 0 <= idx < len(episodes) else {}
    row = get_full(
        conn,
        idx,
        expect_podcast=ep.get("p"),
        expect_episode=ep.get("e"),
    )
    if not row:
        return True
    if row["src"] in ("transcript", "stt", "youtube") and row["chars"] >= min_chars:
        return False
    if row["src"] == "show-notes":
        return True
    return row["chars"] < min_chars


def video_allowed(podcast: str, yt_title: str) -> bool:
    conf = YT_CHANNELS.get(podcast) or {}
    low = (yt_title or "").lower()
    must = conf.get("title_must")
    if must and must not in low:
        return False
    for rej in conf.get("reject_title") or []:
        if rej in low:
            return False
    return True


def match_from_channel(
    podcast: str,
    episodes: list[tuple[int, dict]],
    uploads: list[dict],
    *,
    min_score: float = 0.55,
) -> list[tuple[int, dict, dict]]:
    """Greedy one-to-one match: highest scoring (episode, video) pairs."""
    scored: list[tuple[float, int, int, dict]] = []
    for ei, (idx, ep) in enumerate(episodes):
        title = ep.get("e") or ""
        for vi, vid in enumerate(uploads):
            if not video_allowed(podcast, vid["title"]):
                continue
            sc = title_score(title, vid["title"])
            if sc >= min_score:
                scored.append((sc, ei, vi, vid))
    scored.sort(reverse=True, key=lambda t: t[0])
    used_e: set[int] = set()
    used_v: set[int] = set()
    pairs: list[tuple[int, dict, dict]] = []
    for sc, ei, vi, vid in scored:
        if ei in used_e or vi in used_v:
            continue
        used_e.add(ei)
        used_v.add(vi)
        idx, ep = episodes[ei]
        hit = dict(vid)
        hit["matchScore"] = round(sc, 3)
        pairs.append((idx, ep, hit))
    return pairs


def match_via_search(podcast: str, episode_title: str, search_n: int = 5) -> dict | None:
    hint = YT_SHOW_HINTS.get(podcast, podcast)
    queries = [
        f"{hint} {episode_title}",
        f"{podcast} {episode_title}",
        f'"{episode_title}" {podcast}',
    ]
    results: list[dict] = []
    seen: set[str] = set()
    for q in queries:
        for r in yt_search(q, n=search_n):
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            results.append(r)
        if results:
            break
    if not results:
        return None
    best = None
    best_score = 0.0
    for r in results:
        if not video_allowed(podcast, r["title"]):
            continue
        score = title_score(episode_title, r["title"])
        if score > best_score:
            best_score = score
            best = r
    if not best or best_score < 0.48:
        return None
    best = dict(best)
    best["matchScore"] = round(best_score, 3)
    return best


def build_pairs(
    episodes: list[dict],
    conn,
    *,
    shows: list[str] | None,
    max_episodes: int,
    min_year: int,
    max_minutes: float,
    channel_limit: int,
    search_fallback: bool,
) -> list[tuple[int, dict, dict]]:
    by_show: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for i, ep in enumerate(episodes):
        name = ep.get("p") or ""
        if shows and name not in shows:
            continue
        if not shows and name not in YT_CHANNELS and name not in YT_SHOW_HINTS:
            continue
        year = int(ep.get("y") or 0)
        if year and year < min_year:
            continue
        mins = parse_minutes(ep.get("dur"))
        if max_minutes and mins > max_minutes:
            continue
        if not needs_youtube(conn, i, episodes):
            continue
        by_show[name].append((i, ep))

    for name in by_show:
        by_show[name].sort(key=lambda t: t[1].get("t") or "", reverse=True)

    order = [s for s in PRIORITY_SHOWS if s in by_show]
    order += sorted(k for k in by_show if k not in order)

    pairs: list[tuple[int, dict, dict]] = []
    matched_idxs: set[int] = set()
    per_show: dict[str, list[tuple[int, dict, dict]]] = {}

    # 1) Channel-first (collect per show, then interleave so one show can't eat quota)
    for podcast in order:
        conf = YT_CHANNELS.get(podcast)
        if not conf:
            continue
        print(
            f"[channel] {podcast} → {conf['handle']} (need {len(by_show[podcast])} eps)",
            flush=True,
        )
        uploads = channel_uploads(conf["handle"], limit=channel_limit)
        print(f"  uploads listed={len(uploads)}", flush=True)
        if not uploads:
            continue
        found = match_from_channel(podcast, by_show[podcast], uploads)
        print(f"  channel matches={len(found)}", flush=True)
        per_show[podcast] = found

    pointers = {s: 0 for s in per_show}
    while len(pairs) < max_episodes and any(
        pointers[s] < len(per_show[s]) for s in per_show
    ):
        for s in order:
            if s not in per_show or len(pairs) >= max_episodes:
                continue
            p = pointers[s]
            if p >= len(per_show[s]):
                continue
            idx, ep, vid = per_show[s][p]
            pointers[s] = p + 1
            if idx in matched_idxs:
                continue
            matched_idxs.add(idx)
            pairs.append((idx, ep, vid))

    # 2) Search fallback for remaining high-priority eps
    if search_fallback and len(pairs) < max_episodes:
        print("[search-fallback]", flush=True)
        for podcast in order:
            for idx, ep in by_show[podcast]:
                if idx in matched_idxs:
                    continue
                if len(pairs) >= max_episodes:
                    return pairs
                hit = match_via_search(podcast, ep.get("e") or "")
                if not hit:
                    continue
                matched_idxs.add(idx)
                pairs.append((idx, ep, hit))
                print(
                    f"  search hit {podcast[:30]} ← {hit['id']} "
                    f"score={hit['matchScore']}",
                    flush=True,
                )
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-episodes", type=int, default=90)
    ap.add_argument("--min-year", type=int, default=2020)
    ap.add_argument("--max-minutes", type=float, default=120.0)
    ap.add_argument("--channel-limit", type=int, default=300)
    ap.add_argument("--shows", nargs="*", default=None)
    ap.add_argument("--backends", default="yta,ytapi,transcribe_yt")
    ap.add_argument("--sleep", type=float, default=13.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-search-fallback", action="store_true")
    args = ap.parse_args()

    backends = [b.strip() for b in args.backends.split(",") if b.strip()]
    episodes = json.loads((TABLES / "episodes.json").read_text(encoding="utf-8"))
    conn = connect()

    pairs = build_pairs(
        episodes,
        conn,
        shows=args.shows,
        max_episodes=args.max_episodes,
        min_year=args.min_year,
        max_minutes=args.max_minutes,
        channel_limit=args.channel_limit,
        search_fallback=not args.no_search_fallback,
    )
    print(
        f"pairs={len(pairs)} backends={backends} dry_run={args.dry_run}",
        flush=True,
    )

    stats = {
        "tried": 0,
        "fetched": 0,
        "upserted": 0,
        "noCaptions": 0,
        "rateLimited": 0,
        "errors": [],
        "byBackend": defaultdict(int),
        "byShow": defaultdict(int),
    }

    if args.dry_run:
        for idx, ep, vid in pairs[:40]:
            print(
                f"  DRY {ep.get('p')} | {ep.get('e')[:50]} ← "
                f"{vid['id']} score={vid.get('matchScore')} «{vid['title'][:55]}»",
                flush=True,
            )
        report = {"pairs": len(pairs), "sample": len(pairs[:40])}
        print(json.dumps(report, indent=2))
        conn.close()
        return

    for idx, ep, vid in pairs:
        stats["tried"] += 1
        podcast = ep.get("p") or ""
        title = ep.get("e") or ""
        print(
            f"[{stats['tried']}/{len(pairs)}] {podcast[:36]} — {title[:55]} "
            f"← {vid['id']} ({vid.get('matchScore')})",
            flush=True,
        )
        try:
            text, backend = fetch_captions(vid["id"], backends)
        except RateLimited as rl:
            stats["rateLimited"] += 1
            print(
                f"  RATE LIMITED — stopping (retry_after≈{rl.retry_after})",
                flush=True,
            )
            break
        except Exception as exc:  # noqa: BLE001
            stats["errors"].append(f"fetch {vid['id']}: {exc}")
            print(f"  fetch ERROR {exc}", flush=True)
            continue

        if not text:
            stats["noCaptions"] += 1
            print("  no captions", flush=True)
            time.sleep(min(args.sleep, 3.0))
            continue

        stats["fetched"] += 1
        stats["byBackend"][backend or "?"] += 1
        url = f"https://www.youtube.com/watch?v={vid['id']}"
        upsert_full(
            conn,
            idx,
            text,
            src="youtube",
            podcast=podcast,
            episode=title,
            url=url,
        )
        conn.commit()
        stats["upserted"] += 1
        stats["byShow"][podcast] += 1
        print(f"  OK backend={backend} chars={len(text)}", flush=True)
        time.sleep(args.sleep)

    meta = write_slim_notes(
        conn,
        TABLES / "notes.json",
        TABLES / "notes-meta.json",
        len(episodes),
    )
    report = {
        "harvest": {
            **{
                k: stats[k]
                for k in (
                    "tried",
                    "fetched",
                    "upserted",
                    "noCaptions",
                    "rateLimited",
                )
            },
            "pairs": len(pairs),
            "byBackend": dict(stats["byBackend"]),
            "byShow": dict(stats["byShow"]),
            "errors": stats["errors"][:20],
        },
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
    }
    (TABLES / "youtube-harvest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    conn.close()


if __name__ == "__main__":
    main()
