#!/usr/bin/env python3
"""Match listened episodes to YouTube uploads and harvest caption transcripts.

YouTube blocks most cloud/datacenter IPs for direct caption fetches
(youtube-transcript-api / yt-dlp timedtext). This script tries backends in order:

  1. youtube-transcript-api  — works on residential IPs / with WEBSHARE_* proxies
  2. YTAPI_API_KEY           — optional https://ytapi.dev key (env)
  3. transcribeyoutube.com   — free hosted extractor (no key; fair-use rate limits)
  4. gemini                  — GEMINI_API_KEY; full audio transcription via Gemini
                               video understanding (YouTube URL). Use after free
                               caption backends are exhausted / rate-limited.
                               Long episodes are chunked (default 10 min) via
                               generateContent videoMetadata offsets — whole
                               multi-hour videos exceed the 1M token cap.
                               Free Gemini tier ≈8h YouTube/day; paid key has no
                               daily length cap.

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


def _gemini_quota_exhausted(msg: str) -> bool:
    low = (msg or "").lower()
    return any(
        s in low
        for s in (
            "exceeded your current quota",
            "daily limit",
            "quota exceeded",
            "resource_exhausted",
            "youtube video length",
            "8 hours",
        )
    )


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
                # Surface retry hint when Google returns "Please retry in Nh…"
                retry_hint = None
                m = re.search(
                    r"retry in ([0-9]+h)?([0-9]+m)?([0-9]+(?:\.[0-9]+)?s)?",
                    msg,
                    re.I,
                )
                if m:
                    retry_hint = "".join(g for g in m.groups() if g)
                if _gemini_quota_exhausted(msg) or (
                    "perday" in msg.lower()
                    or "per_day" in msg.lower()
                    or "free_tier_requests" in msg.lower()
                ):
                    print(
                        f"  gemini daily quota exhausted"
                        + (f" (retry in {retry_hint})" if retry_hint else "")
                        + f": {msg[:220]}",
                        flush=True,
                    )
                    raise RateLimited()
                # Soft RPM throttle — wait and retry; raise only after many tries.
                wait = min(180, 30 * (attempt + 1))
                print(
                    f"  gemini {start_s}-{end_s}s 429; backoff {wait}s "
                    f"(attempt {attempt + 1}/{retries})",
                    flush=True,
                )
                if attempt + 1 >= retries:
                    raise RateLimited()
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


def fetch_gemini(video_id: str, duration: int | None = None) -> str | None:
    """Full transcript via Gemini YouTube video understanding (chunked).

    Whole multi-hour episodes exceed the 1M input-token cap under static
    frame sampling. We clip with videoMetadata start/end offsets and
    concatenate. Chunk length defaults to 10 minutes (GEMINI_YT_CHUNK_SECS).
    Completed chunks are cached under transcripts/.gemini_chunks/ so a
    mid-episode 429 can resume on the next run.

    Prefer `duration` from the channel flat-playlist (yt-dlp watch pages are
    often bot-blocked from datacenter IPs).
    """
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        return None
    # Prefer flash-lite: free-tier RPD is per-model; 3.8-flash burns out
    # quickly (20 RPD) while lite handles long chunked XV harvests.
    model = os.environ.get("GEMINI_YT_MODEL", "gemini-3.5-flash-lite")
    chunk_secs = int(os.environ.get("GEMINI_YT_CHUNK_SECS", "600"))
    chunk_secs = max(120, min(chunk_secs, 1800))
    chunk_sleep = float(os.environ.get("GEMINI_YT_CHUNK_SLEEP", "8"))

    if not duration or duration <= 0:
        duration = yt_duration_seconds(video_id)
    if not duration or duration <= 0:
        print("  gemini: could not resolve video duration", flush=True)
        return None

    pieces: list[str] = []
    failed = 0
    n_chunks = (duration + chunk_secs - 1) // chunk_secs
    print(
        f"  gemini chunking duration={duration}s → {n_chunks}×{chunk_secs}s "
        f"model={model}",
        flush=True,
    )
    for i, start in enumerate(range(0, duration, chunk_secs)):
        end = min(start + chunk_secs, duration)
        # Skip tiny trailing slivers (outro logos)
        if end - start < 15 and pieces:
            break
        text = _gemini_generate_chunk(
            key=key,
            model=model,
            video_id=video_id,
            start_s=start,
            end_s=end,
        )
        if text:
            pieces.append(text)
            failed = 0
        else:
            failed += 1
            # Allow a couple of bad chunks (music-only outros) but abort if
            # several consecutive windows fail — likely quota / model outage.
            if failed >= 3:
                print("  gemini: aborting after 3 consecutive chunk failures", flush=True)
                break
        if i + 1 < n_chunks and chunk_sleep > 0:
            time.sleep(chunk_sleep)

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


def fetch_captions(
    video_id: str,
    backends: list[str],
    *,
    duration: int | None = None,
) -> tuple[str | None, str | None]:
    for name in backends:
        if name == "gemini":
            text = fetch_gemini(video_id, duration=duration)
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
    ap.add_argument(
        "--max-minutes",
        type=float,
        default=0.0,
        help="Skip episodes longer than this (0 = no limit). Use 120 without gemini.",
    )
    ap.add_argument("--channel-limit", type=int, default=300)
    ap.add_argument("--shows", nargs="*", default=None)
    ap.add_argument(
        "--backends",
        default="yta,ytapi,transcribe_yt,gemini",
        help="Comma list. gemini needs GEMINI_API_KEY (full YT audio transcription).",
    )
    ap.add_argument("--sleep", type=float, default=13.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-search-fallback", action="store_true")
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
            )
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
