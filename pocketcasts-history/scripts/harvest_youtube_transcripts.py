#!/usr/bin/env python3
"""Match listened episodes to YouTube uploads and harvest caption transcripts.

YouTube blocks most cloud/datacenter IPs for direct caption fetches
(youtube-transcript-api / yt-dlp timedtext). This script tries backends in order:

  1. youtube-transcript-api  — works on residential IPs / with WEBSHARE_* proxies
  2. YTAPI_API_KEY           — optional https://ytapi.dev key (env)
  3. yt_transcript_net       — free https://yt-transcript.net (works from cloud IPs)
  4. transcribeyoutube.com   — free hosted extractor (no key; fair-use rate limits)
  5. gemini                  — GEMINI_API_KEY; full audio transcription via Gemini
                               video understanding (YouTube URL). Use after free
                               caption backends are exhausted / rate-limited.
                               Long episodes are chunked (default 10 min) via
                               generateContent videoMetadata offsets — whole
                               multi-hour videos exceed the 1M token cap.
                               Free Gemini tier ≈8h YouTube/day; paid key has no
                               daily length cap.

Caption backends only work when YouTube already has captions (manual or auto).
They do NOT speech-recognize audio — for caption-less uploads use gemini or STT.

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
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path

from transcript_store import (
    TABLES,
    TRANSCRIPTS,
    connect,
    get_full,
    upsert_full,
    write_slim_notes,
)

UA = "rss-feeds-listening-log/1.1 (+https://github.com/wlad-c/rss-feeds)"
TRANSCRIBE_YT_URL = "https://transcribeyoutube.com/api/transcript"
YT_TRANSCRIPT_NET_URL = "https://yt-transcript.net"

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
        # Podcasts-tab playlist id exists in the UI but yt-dlp gets
        # "playlist does not exist"; channel search returns the series cleanly.
        "channel_search": "ABC News Daily",
        "title_must": "abc news daily",
        # Fallback if search is thin: ~42 titled uploads in latest 1600 videos.
        "channel_limit": 1600,
        # Episode titles are a near-exact prefix of YT
        # "… | ABC News Daily podcast"; low thresholds steal videos via
        # shared Trump/AI tokens onto older unrelated episodes.
        "min_score": 0.85,
        "reject_title": [],
    },
    # VERDICT: full daily Politics Now (~30–50 min) is NOT on YouTube.
    # Only the Insiders On Background subset (~63 feed eps) publishes as a
    # dedicated playlist on @ABCNewsIndepth. Do not search @abcnewsaustralia
    # (Insiders interview clips / no full-show audio). playlist_only keeps
    # harvest scoped to that subset; ordinary Politics Now titles stay unmatched.
    "Politics Now": {
        "handle": "@ABCNewsIndepth",
        "playlist": "PLDTPrMoGHssDd3-ICckOsBZwpp3IEDxYs",
        "playlist_only": True,
        # Playlist is already scoped; some uploads omit the Insiders suffix.
        "title_must": None,
        "min_score": 0.85,
        "reject_title": [
            "abc news daily",
            "news breakfast",
            "7.30",
            "four corners",
            "lateline",
        ],
    },
    # VERDICT: daily Up First full episodes are NOT on YouTube.
    # @nprpodcasts has ~2400 uploads (Throughline, Wait Wait, Code Switch, …)
    # but only 2 titles contain "up first" (Black Stories specials, not dailies).
    # No dedicated @UpFirst channel/playlist; ytsearch only hits fan reuploads
    # (2017–18) or unrelated NPR Morning Edition clips. Prefer NPR publisher
    # transcripts (fetch_publisher_transcripts.py / text.npr.org) for coverage.
    "Up First from NPR": {
        "handle": "@nprpodcasts",
        "title_must": "up first",
        "skip_youtube": True,
        "skip_reason": (
            "Daily Up First episodes are not published as full YouTube videos "
            "(@nprpodcasts has only 2 'Up First' specials, not the daily show)."
        ),
        "reject_title": [],
    },
    "7am": {
        "handle": "@7ampodcast",
        "title_must": None,
        "reject_title": [],
    },
    # Full episodes live on g1's "O Assunto" playlist (legacy @oassunto is stale).
    # EN uploads end with "| THE SUBJECT" / "| THE TOPIC" / "| THE MATTER".
    "O Assunto": {
        "handle": "@g1globo",
        "playlist": "PLU_2p8ieYan5oe6zOciXRO3uPdBsrQrdN",
        "playlist_only": True,
        "title_must": ["o assunto", "the subject", "the topic", "the matter"],
        "reject_title": ["o assunto - cortes", "cortes |"],
        # PT episode titles vs EN YouTube titles score poorly on text alone;
        # blend in duration proximity when the show marker is present.
        "cross_lang": True,
        "search_fallback": True,
    },
    # Full episodes on revista piauí ("Foro de Teresina" / "Teresina Forum").
    "Foro de Teresina": {
        "handle": "@revistapiaui",
        "playlist": "PLn_YkZF2TTNsQjrIOyqOsJilCV9FCtYb7",
        "playlist_only": True,
        "title_must": ["foro de teresina", "teresina forum"],
        "reject_title": ["berro do boi"],
        "cross_lang": True,
    },
    # Weekly politics show; full episodes uploaded on @uol (often as live VODs).
    # Prefer titles with Toledo/Bilenky; reject the unrelated "A Hora e a Vez" series.
    "A Hora": {
        "handle": "@uol",
        "channel_search": "A Hora Toledo Bilenky",
        "title_must": ["a hora"],
        "reject_title": [
            "cortes",
            "shorts",
            "a hora e a vez",
            "a hora e a vez de",
        ],
        "search_fallback": True,
        "min_score": 0.45,
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
    # VERDICT: full Sinica episodes are NOT on YouTube.
    # Probed 2026-10-18: @SinicaPodcast = 5 uploads (China Talking Points +
    # one Ukraine panel); playlists are Panels/Webinars + China Talking Points
    # only. @KaiserKuo is ancient Baidu clips; @TheChinaProject is conference
    # trailers/anniversaries; ytsearch hits third-party interviews (UC Berkeley
    # one-off, Novara, etc.) — not the listened catalog. No usable alternate
    # channel/playlist; leave skip_youtube so harvest does not false-match.
    "Sinica Podcast": {
        "handle": "@SinicaPodcast",
        "skip_youtube": True,
        "skip_reason": (
            "Full Sinica Podcast episodes are not on YouTube "
            "(@SinicaPodcast is China Talking Points only; no alternate "
            "channel/playlist of full episodes found)."
        ),
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
    "A Hora",
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


# Left-side show markers: "Foro de Teresina | episode title"
_SHOW_PREFIX_MARKERS = (
    "foro de teresina",
    "teresina forum",
    "o assunto",
)
# Right-side show markers: "episode title | ABC News Daily podcast"
_SHOW_SUFFIX_MARKERS = (
    "o assunto",
    "the subject",
    "the topic",
    "the matter",
    "abc news daily",
    "politics now",
    "insiders on background",
    "insiders",
    "up first",
)


def _strip_show_suffix(yt_title: str) -> str:
    """Remove show markers from mixed-channel YouTube titles.

    Handles both ``Episode | Show`` (g1, ABC) and ``Show | Episode`` (piauí).
    """
    t = yt_title or ""
    if " | " in t:
        left, right = t.split(" | ", 1)
        left_l = left.strip().lower()
        right_l = right.strip().lower()
        if any(left_l == m or left_l.startswith(m + " ") for m in _SHOW_PREFIX_MARKERS):
            t = right
        elif any(m in right_l for m in _SHOW_SUFFIX_MARKERS):
            t = left
        else:
            # Prefer the longer side as the episode title.
            t = left if len(left) >= len(right) else right
    # Older g1 style: "Title I O ASSUNTO I g1"
    t = re.split(r"\s+[iI]\s+O\s+ASSUNTO\b", t, maxsplit=1)[0]
    t = re.split(r"\s+[iI]\s+THE\s+SUBJECT\b", t, maxsplit=1)[0]
    return t


def title_score(ep_title: str, yt_title: str) -> float:
    # Strip show markers from both sides (feed titles often keep "| Insiders…").
    a = normalize(_strip_show_suffix(ep_title))
    b = normalize(_strip_show_suffix(yt_title))
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
        if a.startswith(prefix):
            a = a[len(prefix) :]
    seq = SequenceMatcher(None, a, b).ratio()
    ta, tb = token_set(a), token_set(b)
    jacc = (len(ta & tb) / len(ta | tb)) if ta and tb else 0.0
    contain = 1.0 if (a in b or b in a) else 0.0
    # Shared distinctive tokens (longer words / digits) help PT↔EN pairs.
    proper = {t for t in (ta & tb) if len(t) >= 4 or any(ch.isdigit() for ch in t)}
    proper_boost = min(0.25, 0.08 * len(proper))
    return min(1.0, 0.45 * seq + 0.45 * jacc + 0.10 * contain + proper_boost)


def duration_score(ep_dur: str | None, yt_seconds: int | None) -> float:
    """1.0 when lengths nearly match; 0 when unknown or far apart."""
    mins = parse_minutes(ep_dur)
    if not mins or not yt_seconds or yt_seconds <= 0:
        return 0.0
    ep_s = mins * 60.0
    ratio = abs(ep_s - float(yt_seconds)) / max(ep_s, float(yt_seconds))
    if ratio <= 0.06:
        return 1.0
    if ratio <= 0.12:
        return 0.8
    if ratio <= 0.20:
        return 0.5
    if ratio <= 0.30:
        return 0.25
    return 0.0


def episode_video_score(
    podcast: str, ep: dict, yt_title: str, yt_duration: int | None
) -> float:
    """Composite match score; duration-aware for cross-language shows."""
    conf = YT_CHANNELS.get(podcast) or {}
    ep_title = ep.get("e") or ""
    tscore = title_score(ep_title, yt_title)
    if not conf.get("cross_lang"):
        return tscore
    dscore = duration_score(ep.get("dur"), yt_duration)
    ta = token_set(_strip_show_suffix(ep_title))
    tb = token_set(_strip_show_suffix(yt_title))
    # Include 3-letter acronyms (TSE, STF, PCC) as anchors for PT↔EN pairs.
    shared = {
        t
        for t in (ta & tb)
        if len(t) >= 4
        or any(ch.isdigit() for ch in t)
        or (len(t) == 3 and t.isalpha())
    }
    # Duration alone is dangerous on a ~30min daily show — require lexical anchors.
    if len(shared) >= 2 and dscore >= 0.5:
        return min(
            1.0,
            0.50 * tscore + 0.35 * dscore + 0.15 * min(1.0, len(shared) / 3.0),
        )
    # Show-tagged upload (caller already filtered title_must) + one proper
    # noun/acronym + near-equal duration is enough for EN g1 titles.
    if len(shared) >= 1 and dscore >= 0.8:
        return min(1.0, 0.40 * tscore + 0.45 * dscore + 0.15)
    # Dedicated show playlist: near-equal duration + weak lexical overlap can
    # still be trusted (pure PT↔EN with no shared proper nouns).
    if conf.get("playlist_only") and dscore >= 0.9 and tscore >= 0.12:
        return min(1.0, 0.35 * tscore + 0.55 * dscore + 0.10)
    return tscore


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


def _yt_dlp_bin() -> str:
    """Resolve yt-dlp even when ~/.local/bin is not on PATH."""
    for candidate in (
        os.environ.get("YT_DLP_BIN"),
        "yt-dlp",
        str(Path.home() / ".local/bin/yt-dlp"),
        "/usr/local/bin/yt-dlp",
    ):
        if not candidate:
            continue
        if candidate == "yt-dlp":
            return candidate
        if Path(candidate).is_file():
            return candidate
    return "yt-dlp"


def yt_dump(url_or_query: str, limit: int = 50) -> list[dict]:
    cmd = [
        _yt_dlp_bin(),
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
        dur = j.get("duration")
        try:
            dur_i = int(float(dur)) if dur is not None else None
        except (TypeError, ValueError):
            dur_i = None
        out.append(
            {
                "id": vid,
                "title": j.get("title") or "",
                "uploader": j.get("uploader") or j.get("channel") or "",
                "url": j.get("url") or f"https://www.youtube.com/watch?v={vid}",
                "duration": dur_i,
            }
        )
    return out


def yt_search(query: str, n: int = 5) -> list[dict]:
    return yt_dump(f"ytsearch{n}:{query}", limit=n)


def channel_uploads(handle: str, limit: int = 250) -> list[dict]:
    handle = handle if handle.startswith("@") else f"@{handle}"
    return yt_dump(f"https://www.youtube.com/{handle}/videos", limit=limit)


def playlist_videos(playlist_id: str, limit: int = 500) -> list[dict]:
    """Fetch a playlist; returns [] if YouTube reports it missing (common for
    Podcasts-tab series ids that are not enumerable as classic playlists)."""
    pid = (playlist_id or "").strip()
    if not pid:
        return []
    if pid.startswith("http"):
        url = pid
    else:
        url = f"https://www.youtube.com/playlist?list={pid}"
    return yt_dump(url, limit=limit)


def channel_search_videos(handle: str, query: str, limit: int = 300) -> list[dict]:
    """Videos from a channel's search tab (often denser than /videos for series)."""
    handle = handle if str(handle).startswith("@") else f"@{handle}"
    q = urllib.parse.quote_plus(query)
    return yt_dump(
        f"https://www.youtube.com/{handle}/search?query={q}",
        limit=limit,
    )


def show_video_pool(conf: dict, channel_limit: int) -> list[dict]:
    """Playlist / channel-search / uploads pool for a show."""
    limit = int(conf.get("channel_limit") or channel_limit or 300)
    by_id: dict[str, dict] = {}
    pl = conf.get("playlist")
    if pl:
        for v in playlist_videos(str(pl), limit=max(limit, 500)):
            by_id[v["id"]] = v
        if by_id:
            print(f"  playlist listed={len(by_id)}", flush=True)
        else:
            print(
                f"  playlist {pl} empty/unavailable — falling back",
                flush=True,
            )
    handle = conf.get("handle")
    search_q = conf.get("channel_search")
    search_hits = 0
    if handle and search_q:
        found = channel_search_videos(handle, str(search_q), limit=max(limit, 300))
        search_hits = len(found)
        for v in found:
            by_id[v["id"]] = v
        print(f"  channel search listed={search_hits}", flush=True)
    # Skip broad /videos crawl when playlist_only or channel_search already
    # filled the pool; still fall back to uploads if those sources were empty.
    skip_uploads = bool(by_id) and (
        bool(conf.get("playlist_only")) or bool(search_q and search_hits)
    )
    if handle and not skip_uploads:
        for v in channel_uploads(handle, limit=limit):
            by_id[v["id"]] = v
    return list(by_id.values())


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


class EpisodeClaimed(Exception):
    """Another parallel worker already owns this video_id."""


def fetch_yt_transcript_net(video_id: str) -> str | None:
    """Free caption relay that works from many cloud IPs (no API key).

    Returns None for videos without captions (HTTP 404) or transient failures.
    """
    url = f"{YT_TRANSCRIPT_NET_URL}/{urllib.parse.quote(video_id)}?fmt=text"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "text/plain, */*"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RateLimited()
        return None
    except Exception:  # noqa: BLE001
        return None
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if len(text) >= 80 else None


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


GEMINI_CHUNK_PROMPT = (
    "Transcribe this clip verbatim in the original language. Output plain text "
    "only — no commentary, no title, no markdown fences. Preserve natural "
    "paragraph breaks. Do not summarize or omit segments."
)


def yt_duration_seconds(video_id: str) -> int | None:
    """Wall-clock duration via yt-dlp (needed to chunk long Gemini jobs)."""
    cmd = [
        _yt_dlp_bin(),
        "--print",
        "%(duration)s",
        "--no-warnings",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    line = (proc.stdout or "").strip().splitlines()
    if not line:
        return None
    try:
        return int(float(line[0]))
    except ValueError:
        return None


def _gemini_strip_preamble(text: str) -> str:
    text = (text or "").strip()
    for prefix in (
        "Here is the full transcript",
        "Here's the full transcript",
        "Here is the transcript",
        "Here's the transcript",
        "Transcript:",
        "Full transcript:",
    ):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix) :].lstrip(" \n:")
            break
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _gemini_chunk_dir(video_id: str) -> Path:
    d = TRANSCRIPTS / ".gemini_chunks" / video_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _gemini_chunk_path(video_id: str, start_s: int, end_s: int) -> Path:
    return _gemini_chunk_dir(video_id) / f"{start_s:06d}-{end_s:06d}.txt"


def _gemini_load_chunk(video_id: str, start_s: int, end_s: int) -> str | None:
    path = _gemini_chunk_path(video_id, start_s, end_s)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text if len(text) >= 40 else None


def _gemini_save_chunk(video_id: str, start_s: int, end_s: int, text: str) -> None:
    path = _gemini_chunk_path(video_id, start_s, end_s)
    path.write_text(text, encoding="utf-8")


def _gemini_clear_chunks(video_id: str) -> None:
    d = TRANSCRIPTS / ".gemini_chunks" / video_id
    if not d.is_dir():
        return
    for p in d.glob("*.txt"):
        try:
            p.unlink()
        except OSError:
            pass
    try:
        d.rmdir()
    except OSError:
        pass


def _gemini_claim_path(video_id: str) -> Path:
    d = TRANSCRIPTS / ".gemini_chunks" / ".claims"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{video_id}.claim"


def _gemini_try_claim(video_id: str) -> bool:
    """Exclusive in-progress lock so parallel workers don't double-fetch."""
    path = _gemini_claim_path(video_id)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # Stale claim (>6h) → steal; else skip.
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            age = 0
        if age < 6 * 3600:
            return False
        try:
            path.unlink()
        except OSError:
            return False
        return _gemini_try_claim(video_id)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(f"pid={os.getpid()} ts={time.time():.0f}\n")
    return True


def _gemini_release_claim(video_id: str) -> None:
    try:
        _gemini_claim_path(video_id).unlink()
    except OSError:
        pass


def _gemini_parse_retry_seconds(msg: str) -> float | None:
    """Parse 'Please retry in 20h59m7s' / '48.4s' into seconds."""
    m = re.search(
        r"retry in\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+(?:\.\d+)?)\s*s)?",
        msg or "",
        re.I,
    )
    if not m:
        return None
    h = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    secs = float(m.group(3) or 0)
    total = h * 3600 + mins * 60 + secs
    return total if total > 0 else None


def _gemini_daily_quota(msg: str) -> bool:
    """True when Google is telling us to wait hours (day bucket), not seconds (RPM)."""
    low = (msg or "").lower()
    retry_s = _gemini_parse_retry_seconds(msg) or 0
    if retry_s >= 3600:
        return True
    if "perday" in low or "per_day" in low or "per-day" in low:
        return retry_s >= 600  # day metric with long retry
    if "youtube" in low and ("8 hour" in low or "daily" in low):
        return True
    return False


def _gemini_generate_chunk(
    *,
    key: str,
    model: str,
    video_id: str,
    start_s: int,
    end_s: int,
    retries: int = 8,
) -> str | None:
    """Transcribe [start_s, end_s) via generateContent + videoMetadata offsets."""
    cached = _gemini_load_chunk(video_id, start_s, end_s)
    if cached:
        print(
            f"  gemini chunk {start_s}-{end_s}s chars={len(cached)} (cache)",
            flush=True,
        )
        return cached

    yt_url = f"https://www.youtube.com/watch?v={video_id}"
    body = {
        "contents": [
            {
                "parts": [
                    {"text": GEMINI_CHUNK_PROMPT},
                    {
                        "file_data": {"file_uri": yt_url},
                        "video_metadata": {
                            "start_offset": f"{start_s}s",
                            "end_offset": f"{end_s}s",
                        },
                    },
                ]
            }
        ],
        "generationConfig": {
            # LOW keeps ~3h of video under the 1M context; we chunk further.
            "mediaResolution": "MEDIA_RESOLUTION_LOW",
            "maxOutputTokens": 8192,
        },
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    last_err = ""
    for attempt in range(retries):
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "User-Agent": UA,
                "Content-Type": "application/json",
                "x-goog-api-key": key,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            payload = b""
            try:
                payload = exc.read()
            except Exception:  # noqa: BLE001
                pass
            msg = payload.decode("utf-8", errors="replace")
            last_err = f"HTTP {exc.code}: {msg[:240]}"
            if exc.code == 429:
                retry_s = _gemini_parse_retry_seconds(msg)
                if _gemini_daily_quota(msg):
                    hint = f"{retry_s:.0f}s" if retry_s else "?"
                    print(
                        f"  gemini daily quota exhausted (retry in ~{hint}): "
                        f"{msg[:220]}",
                        flush=True,
                    )
                    raise RateLimited(retry_s)
                # Soft RPM / burst throttle — honor server hint when present.
                wait = retry_s if retry_s and retry_s < 3600 else min(
                    180, 20 * (attempt + 1)
                )
                wait = max(5.0, min(wait + 2.0, 300.0))
                print(
                    f"  gemini {start_s}-{end_s}s 429; backoff {wait:.0f}s "
                    f"(attempt {attempt + 1}/{retries})",
                    flush=True,
                )
                if attempt + 1 >= retries:
                    raise RateLimited(retry_s)
                time.sleep(wait)
                continue
            if exc.code in (503, 500, 502, 504) and attempt + 1 < retries:
                wait = min(90, 4 * (2**attempt))
                print(
                    f"  gemini {start_s}-{end_s}s {exc.code}; retry in {wait}s",
                    flush=True,
                )
                time.sleep(wait)
                continue
            print(f"  gemini {start_s}-{end_s}s {last_err}", flush=True)
            return None
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            if attempt + 1 < retries:
                wait = min(60, 4 * (2**attempt))
                print(
                    f"  gemini {start_s}-{end_s}s error {exc}; retry in {wait}s",
                    flush=True,
                )
                time.sleep(wait)
                continue
            print(f"  gemini {start_s}-{end_s}s error: {exc}", flush=True)
            return None

        cands = (data or {}).get("candidates") or []
        if not cands:
            last_err = f"no candidates: {json.dumps(data)[:240]}"
            if attempt + 1 < retries:
                time.sleep(min(30, 3 * (attempt + 1)))
                continue
            print(f"  gemini {start_s}-{end_s}s {last_err}", flush=True)
            return None
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(
            p.get("text") or ""
            for p in parts
            if isinstance(p, dict) and p.get("text") and not p.get("thought")
        )
        text = _gemini_strip_preamble(text)
        finish = cands[0].get("finishReason") or cands[0].get("finish_reason")
        usage = (data or {}).get("usageMetadata") or {}
        print(
            f"  gemini chunk {start_s}-{end_s}s chars={len(text)} "
            f"finish={finish} promptTok={usage.get('promptTokenCount')}",
            flush=True,
        )
        if len(text) >= 40:
            _gemini_save_chunk(video_id, start_s, end_s, text)
            return text
        return None
    print(f"  gemini {start_s}-{end_s}s failed: {last_err}", flush=True)
    return None


def fetch_gemini(
    video_id: str,
    duration: int | None = None,
    *,
    model: str | None = None,
    parallel: int | None = None,
) -> str | None:
    """Full transcript via Gemini YouTube video understanding (chunked).

    Whole multi-hour episodes exceed the 1M input-token cap under static
    frame sampling. We clip with videoMetadata start/end offsets and
    concatenate. Chunk length defaults to 10 minutes (GEMINI_YT_CHUNK_SECS).
    Completed chunks are cached under transcripts/.gemini_chunks/ so a
    mid-episode 429 can resume on the next run. Set parallel>1 to fetch
    windows concurrently (biggest wall-clock win on free tier).

    Prefer `duration` from the channel flat-playlist (yt-dlp watch pages are
    often bot-blocked from datacenter IPs).
    """
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        return None
    # Prefer flash-lite: free-tier RPD is per-model; 3.8-flash burns out
    # quickly (20 RPD) while lite handles long chunked XV harvests.
    model = model or os.environ.get("GEMINI_YT_MODEL", "gemini-3.1-flash-lite")
    chunk_secs = int(os.environ.get("GEMINI_YT_CHUNK_SECS", "600"))
    chunk_secs = max(120, min(chunk_secs, 1800))
    chunk_sleep = float(os.environ.get("GEMINI_YT_CHUNK_SLEEP", "2"))
    workers = parallel if parallel is not None else int(
        os.environ.get("GEMINI_YT_PARALLEL", "4")
    )
    workers = max(1, min(workers, 12))

    if not duration or duration <= 0:
        duration = yt_duration_seconds(video_id)
    if not duration or duration <= 0:
        print("  gemini: could not resolve video duration", flush=True)
        return None

    if not _gemini_try_claim(video_id):
        print(
            f"  gemini: skip {video_id} — already claimed by another worker",
            flush=True,
        )
        raise EpisodeClaimed(video_id)

    windows: list[tuple[int, int]] = []
    for start in range(0, duration, chunk_secs):
        end = min(start + chunk_secs, duration)
        if end - start < 15 and windows:
            break
        windows.append((start, end))
    n_chunks = len(windows)
    print(
        f"  gemini chunking duration={duration}s → {n_chunks}×{chunk_secs}s "
        f"model={model} parallel={workers}",
        flush=True,
    )

    results: dict[int, str | None] = {}
    rate_limited = False

    def _one(window: tuple[int, int]) -> tuple[int, int, str | None]:
        start_s, end_s = window
        text = _gemini_generate_chunk(
            key=key,
            model=model,
            video_id=video_id,
            start_s=start_s,
            end_s=end_s,
        )
        return start_s, end_s, text

    try:
        if workers == 1:
            for i, window in enumerate(windows):
                try:
                    start_s, end_s, text = _one(window)
                except RateLimited:
                    rate_limited = True
                    break
                results[start_s] = text
                if i + 1 < n_chunks and chunk_sleep > 0:
                    time.sleep(chunk_sleep)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {pool.submit(_one, w): w for w in windows}
                for fut in as_completed(futs):
                    try:
                        start_s, end_s, text = fut.result()
                        results[start_s] = text
                    except RateLimited:
                        rate_limited = True
                        for other in futs:
                            other.cancel()
                        break
                    except Exception as exc:  # noqa: BLE001
                        start_s, end_s = futs[fut]
                        print(
                            f"  gemini chunk {start_s}-{end_s}s worker error: {exc}",
                            flush=True,
                        )
                        results[start_s] = None
        if rate_limited:
            raise RateLimited()

        pieces: list[str] = []
        failed = 0
        for start_s, end_s in windows:
            text = results.get(start_s)
            if text:
                pieces.append(text)
                failed = 0
            else:
                failed += 1
                if failed >= 3:
                    print(
                        "  gemini: aborting after 3 consecutive chunk failures",
                        flush=True,
                    )
                    break

        if not pieces:
            return None
        joined = _gemini_strip_preamble("\n\n".join(pieces))
        # Require a plausible fraction of the episode (very short → incomplete).
        min_chars = max(500, min(8000, duration // 2))
        if len(joined) < min_chars:
            print(
                f"  gemini: joined transcript too short "
                f"({len(joined)} chars for {duration}s; need ≥{min_chars})",
                flush=True,
            )
            return None
        # Full episode assembled — drop resume cache.
        _gemini_clear_chunks(video_id)
        return joined
    finally:
        _gemini_release_claim(video_id)


def fetch_captions(
    video_id: str,
    backends: list[str],
    *,
    duration: int | None = None,
    gemini_model: str | None = None,
    gemini_parallel: int | None = None,
) -> tuple[str | None, str | None]:
    for name in backends:
        if name == "gemini":
            text = fetch_gemini(
                video_id,
                duration=duration,
                model=gemini_model,
                parallel=gemini_parallel,
            )
            if text:
                return text, "gemini"
        elif name == "yta":
            text = fetch_yta(video_id)
            if text:
                return text, "yta"
        elif name == "ytapi":
            text = fetch_ytapi(video_id)
            if text:
                return text, "ytapi"
        elif name == "yt_transcript_net":
            text = fetch_yt_transcript_net(video_id)
            if text:
                return text, "yt_transcript_net"
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
    if must:
        musts = must if isinstance(must, (list, tuple)) else [must]
        if not any(m.lower() in low for m in musts):
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
    conf = YT_CHANNELS.get(podcast) or {}
    # Cross-lang: allow slightly below default once duration+shared tokens lift.
    # Per-show min_score (e.g. ABC News Daily 0.85) beats the call default.
    if conf.get("cross_lang"):
        thr = float(conf.get("min_score") or 0.48)
    else:
        thr = float(conf.get("min_score") or min_score)
    scored: list[tuple[float, int, int, dict]] = []
    for ei, (idx, ep) in enumerate(episodes):
        for vi, vid in enumerate(uploads):
            if not video_allowed(podcast, vid["title"]):
                continue
            sc = episode_video_score(
                podcast, ep, vid["title"], vid.get("duration")
            )
            if sc >= thr:
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


def match_via_search(
    podcast: str,
    episode_title: str,
    search_n: int = 5,
    *,
    ep: dict | None = None,
) -> dict | None:
    hint = YT_SHOW_HINTS.get(podcast, podcast)
    conf = YT_CHANNELS.get(podcast) or {}
    cross = bool(conf.get("cross_lang") or podcast == "O Assunto")
    # Primary queries first — rank-1 + duration is a strong PT↔EN signal.
    if cross:
        primary_queries = [
            f"{episode_title} O ASSUNTO",
            f"{episode_title} THE SUBJECT",
        ]
        secondary_queries = [
            f"O ASSUNTO {episode_title}",
            f"{hint} {episode_title}",
            f"{podcast} {episode_title}",
            f'"{episode_title}" {podcast}',
        ]
    else:
        primary_queries = []
        secondary_queries = [
            f"{hint} {episode_title}",
            f"{podcast} {episode_title}",
            f'"{episode_title}" {podcast}',
        ]

    ep_dict = ep or {"e": episode_title}
    best = None
    best_score = 0.0
    seen: set[str] = set()

    def consider(r: dict, *, primary_rank: int | None) -> None:
        nonlocal best, best_score
        if not video_allowed(podcast, r["title"]):
            return
        score = episode_video_score(
            podcast, ep_dict, r["title"], r.get("duration")
        )
        dscore = duration_score(ep_dict.get("dur"), r.get("duration"))
        # Exact-title search + show marker: trust top hit when length fits.
        if primary_rank is not None and primary_rank == 0 and dscore >= 0.5:
            score = max(score, 0.42 + 0.40 * dscore + 0.18 * min(score, 1.0))
        elif primary_rank is not None and primary_rank <= 2 and dscore >= 0.8:
            score = max(score, 0.36 + 0.35 * dscore + 0.20 * min(score, 1.0))
        if score > best_score:
            best_score = score
            best = r

    for q in primary_queries:
        hits = yt_search(q, n=search_n)
        for rank, r in enumerate(hits):
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            consider(r, primary_rank=rank)
        if best_score >= 0.55:
            break

    if best_score < 0.55:
        for q in secondary_queries:
            for r in yt_search(q, n=search_n):
                if r["id"] in seen:
                    continue
                seen.add(r["id"])
                consider(r, primary_rank=None)
            if best_score >= 0.55 or (best and not cross):
                break

    if conf.get("min_score") is not None:
        thr = float(conf["min_score"])
    elif cross:
        thr = 0.45
    else:
        thr = 0.48
    if not best or best_score < thr:
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
    # Pool = all year/duration-eligible episodes (for correct video ownership).
    # Need = subset still missing a long transcript (what we harvest).
    pool_by_show: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    need_by_show: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    need_idxs: set[int] = set()

    for i, ep in enumerate(episodes):
        name = ep.get("p") or ""
        if shows and name not in shows:
            continue
        conf = YT_CHANNELS.get(name)
        if conf and conf.get("skip_youtube"):
            continue
        if not shows and name not in YT_CHANNELS and name not in YT_SHOW_HINTS:
            continue
        year = int(ep.get("y") or 0)
        if year and year < min_year:
            continue
        mins = parse_minutes(ep.get("dur"))
        if max_minutes and mins > max_minutes:
            continue
        pool_by_show[name].append((i, ep))
        if needs_youtube(conn, i, episodes):
            need_by_show[name].append((i, ep))
            need_idxs.add(i)

    for name in pool_by_show:
        pool_by_show[name].sort(key=lambda t: t[1].get("t") or "", reverse=True)
        need_by_show[name].sort(key=lambda t: t[1].get("t") or "", reverse=True)

    # Surface skip_youtube shows when explicitly requested so logs document why.
    if shows:
        for name in shows:
            conf = YT_CHANNELS.get(name) or {}
            if conf.get("skip_youtube"):
                reason = conf.get("skip_reason") or "configured skip_youtube"
                print(f"[skip] {name}: {reason}", flush=True)

    order = [s for s in PRIORITY_SHOWS if s in need_by_show]
    order += sorted(k for k in need_by_show if k not in order)

    pairs: list[tuple[int, dict, dict]] = []
    matched_idxs: set[int] = set()
    matched_vids: set[str] = set()
    per_show: dict[str, list[tuple[int, dict, dict]]] = {}

    # 1) Channel/playlist-first (match against full pool, keep need-only pairs)
    for podcast in order:
        conf = YT_CHANNELS.get(podcast)
        if not conf:
            continue
        print(
            f"[channel] {podcast} → {conf['handle']} "
            f"(need {len(need_by_show[podcast])} / pool {len(pool_by_show[podcast])} eps)",
            flush=True,
        )
        uploads = show_video_pool(conf, channel_limit)
        print(f"  video pool listed={len(uploads)}", flush=True)
        if not uploads:
            continue
        found_all = match_from_channel(podcast, pool_by_show[podcast], uploads)
        found = [(i, e, v) for i, e, v in found_all if i in need_idxs]
        print(
            f"  channel matches={len(found)} "
            f"(of {len(found_all)} incl. already-covered)",
            flush=True,
        )
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
            vid_id = vid.get("id") or ""
            if idx in matched_idxs or (vid_id and vid_id in matched_vids):
                continue
            matched_idxs.add(idx)
            if vid_id:
                matched_vids.add(vid_id)
            pairs.append((idx, ep, vid))

    # 2) Search fallback for remaining high-priority eps
    if search_fallback and len(pairs) < max_episodes:
        print("[search-fallback]", flush=True)
        for podcast in order:
            conf = YT_CHANNELS.get(podcast) or {}
            if conf.get("skip_youtube"):
                continue
            for idx, ep in need_by_show[podcast]:
                if idx in matched_idxs:
                    continue
                if len(pairs) >= max_episodes:
                    return pairs
                hit = match_via_search(podcast, ep.get("e") or "", ep=ep)
                if not hit:
                    continue
                vid_id = hit.get("id") or ""
                if vid_id and vid_id in matched_vids:
                    continue
                matched_idxs.add(idx)
                if vid_id:
                    matched_vids.add(vid_id)
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
    ap.add_argument(
        "--max-minutes",
        type=float,
        default=0.0,
        help="Skip episodes longer than this (0 = no limit). Use 120 without gemini.",
    )
    ap.add_argument(
        "--channel-limit",
        type=int,
        default=1600,
        help="Max channel uploads to list (per-show channel_limit in YT_CHANNELS wins).",
    )
    ap.add_argument("--shows", nargs="*", default=None)
    ap.add_argument(
        "--backends",
        default="yta,ytapi,yt_transcript_net,transcribe_yt,gemini",
        help="Comma list. gemini needs GEMINI_API_KEY (full YT audio transcription).",
    )
    ap.add_argument("--sleep", type=float, default=13.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-search-fallback", action="store_true")
    ap.add_argument(
        "--gemini-model",
        default=None,
        help="Override GEMINI_YT_MODEL (shard workers across models for free-tier RPD).",
    )
    ap.add_argument(
        "--gemini-parallel",
        type=int,
        default=None,
        help="Concurrent chunk requests per episode (default 4 / GEMINI_YT_PARALLEL).",
    )
    args = ap.parse_args()

    backends = [b.strip() for b in args.backends.split(",") if b.strip()]
    if "gemini" in backends and not (
        os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    ):
        print(
            "WARN: gemini backend selected but GEMINI_API_KEY unset — skipping it",
            flush=True,
        )
        backends = [b for b in backends if b != "gemini"]
    if not backends and not args.dry_run:
        raise SystemExit(
            "no transcript backends available (set GEMINI_API_KEY for gemini)"
        )
    if args.gemini_model:
        os.environ["GEMINI_YT_MODEL"] = args.gemini_model
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
        f"pairs={len(pairs)} backends={backends} dry_run={args.dry_run} "
        f"gemini_model={args.gemini_model or os.environ.get('GEMINI_YT_MODEL', 'gemini-3.1-flash-lite')} "
        f"gemini_parallel={args.gemini_parallel or os.environ.get('GEMINI_YT_PARALLEL', '4')}",
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
            dur = vid.get("duration")
            if not dur:
                # Fall back to Pocket Casts episode length (minutes → seconds)
                mins = parse_minutes(ep.get("dur"))
                if mins and mins > 0:
                    dur = int(mins * 60)
            text, backend = fetch_captions(
                vid["id"],
                backends,
                duration=dur,
                gemini_model=args.gemini_model,
                gemini_parallel=args.gemini_parallel,
            )
        except EpisodeClaimed:
            print("  skipped (claimed by peer worker)", flush=True)
            continue
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
