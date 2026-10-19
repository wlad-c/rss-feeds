#!/usr/bin/env python3
"""Selective STT for high-value episodes missing publisher transcripts.

Free backends only (no paid API):
  - faster-whisper — local CPU (default workhorse)
  - notetakers — free public STT (10 req/day/IP, no key)
  - auto — try NoteTakers first (up to daily cap), then local Whisper

Prioritizes top shows, recent years, shorter episodes.
Stores FULL text in transcripts/full.sqlite (src=stt).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from transcript_store import TABLES, connect, get_full, upsert_full, write_slim_notes

EPISODES_CSV = TABLES / "episodes.csv"
# Persistent skip list for dead audio URLs (404) so waves do not re-burn them.
STT_SKIP_PATH = TABLES.parent / "transcripts" / "stt-skip.json"

UA = "rss-feeds-listening-log/1.1 (+https://github.com/wlad-c/rss-feeds)"
# Prefer shows that lack reliable YouTube captions / publisher transcripts.
# Caption-rich shows (The Daily, ABC News Daily, Ezra) are harvested via
# yt_transcript_net — do not burn STT quota on them first.
PRIORITY_SHOWS = [
    "The Morning Edition",
    "Up First from NPR",
    "Politics Now",  # only Insiders On Background subset is on YT
    "Global Roaming with Geraldine Doogue and Hamish Macdonald",
    "Morning Brief",
    "Australian Politics",
    "Democracy Sausage with Mark Kenny",
    "The National Security Podcast",
    "Asia Geopolitics",
    "Sources & Methods",
    "The Run-Up",
    "7am",
    "ABC News Daily",
    "The Daily",
]


def normalize(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
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


def parse_audio_map(xml_text: str) -> dict[str, str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        xml_text = re.sub(r"&(?!amp;|lt;|gt;|apos;|quot;)", "&amp;", xml_text)
        root = ET.fromstring(xml_text)
    out: dict[str, str] = {}
    for elem in root.iter():
        if local(elem.tag) != "item":
            continue
        title = ""
        audio = ""
        for child in list(elem):
            tag = local(child.tag)
            if tag == "title":
                title = (child.text or "").strip()
            elif tag == "enclosure":
                url = child.attrib.get("url") or ""
                typ = child.attrib.get("type") or ""
                if url and ("audio" in typ or url.endswith((".mp3", ".m4a", ".aac"))):
                    audio = url
        if title and audio:
            out[normalize(title)] = audio
    return out


def dur_minutes(ep: dict) -> float:
    d = str(ep.get("dur") or "")
    parts = d.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60
        if len(parts) == 2:
            return int(parts[0]) + int(parts[1]) / 60
    except ValueError:
        return 25.0
    return 25.0


def already_good(
    conn, idx: int, episodes: list[dict], min_chars: int = 2000
) -> bool:
    """Skip episodes that already have a reliable full transcript.

    Treat publisher transcripts and YouTube captions as authoritative when
    they are long enough — never burn STT over a solid caption/transcript.
    Short publisher stubs (<1200 chars) may still be upgraded by STT
    (transcript_store trust order allows that). Any prior STT attempt with
    usable text is treated as done so we do not re-Whisper the same clip.
    """
    ep = episodes[idx] if 0 <= idx < len(episodes) else {}
    row = get_full(
        conn,
        idx,
        expect_podcast=ep.get("p"),
        expect_episode=ep.get("e"),
    )
    if not row:
        return False
    src = row["src"]
    chars = int(row["chars"] or 0)
    # Publisher / YouTube captions are highest-trust free sources.
    if src in ("transcript", "youtube") and chars >= 1200:
        return True
    # Already STT'd (including short promos) — do not re-burn CPU.
    if src == "stt" and chars >= 80:
        return True
    return False


def audio_url_ok(url: str) -> bool:
    """Cheap preflight: skip known-dead enclosures before download/transcribe."""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": UA}, method="HEAD"
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            if int(code) >= 400:
                return False
            cl = resp.headers.get("Content-Length")
            if cl is not None and int(cl) < 8000:
                return False
            return True
    except Exception:  # noqa: BLE001
        # Some CDNs reject HEAD; fall through to GET download.
        return True


def download_audio(url: str, dest: Path) -> None:
    # stream to file
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


def to_wav_16k(src: Path, wav: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-vn",
            str(wav),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


_whisper_model = None


def load_wav_mono_f32(wav: Path) -> "object":
    """Load 16-bit PCM wav as float32 mono array (avoids broken PyAV builds)."""
    import wave

    import numpy as np

    with wave.open(str(wav), "rb") as w:
        assert w.getnchannels() == 1, "expected mono wav"
        assert w.getsampwidth() == 2, "expected 16-bit wav"
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe_faster_whisper(wav: Path, model_size: str = "base") -> str:
    global _whisper_model
    from faster_whisper import WhisperModel

    if _whisper_model is None:
        print(f"  loading faster-whisper model={model_size}", flush=True)
        _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
    # Pass ndarray — some environments ship PyAV without metadata_errors support.
    audio = load_wav_mono_f32(wav)
    segments, _info = _whisper_model.transcribe(audio, vad_filter=True, language=None)
    parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def transcribe_notetakers(audio_path: Path, language: str | None = None) -> str:
    """Free public STT: https://notetakers.vipresearch.ca/stt (10/day/IP)."""
    import urllib.error
    from urllib.request import Request

    boundary = f"----stt{int(time.time())}"
    file_bytes = audio_path.read_bytes()
    filename = audio_path.name or "audio.mp3"
    fields = [
        (b"engine", b"whisper"),
    ]
    if language:
        fields.append((b"language", language.encode()))
    body = bytearray()
    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name.decode()}"\r\n\r\n'.encode())
        body.extend(value + b"\r\n")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    )
    body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
    body.extend(file_bytes + b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    req = Request(
        "https://notetakers.vipresearch.ca/stt/v1/transcribe",
        data=bytes(body),
        headers={
            "User-Agent": UA,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"notetakers HTTP {exc.code}: {detail}") from exc
    if not data.get("success"):
        raise RuntimeError(f"notetakers failed: {data}")
    text = (data.get("text") or "").strip()
    if len(text) < 80:
        raise RuntimeError(f"notetakers short text ({len(text)})")
    return re.sub(r"\s+", " ", text).strip()


def transcribe(
    audio_path: Path,
    wav: Path,
    *,
    engine: str,
    model_size: str,
    notetakers_left: list[int],
) -> tuple[str, str]:
    """Return (text, engine_used). notetakers_left is a 1-item mutable counter."""
    if engine in ("notetakers", "auto") and notetakers_left[0] > 0:
        try:
            text = transcribe_notetakers(audio_path)
            notetakers_left[0] -= 1
            return text, "notetakers"
        except Exception as exc:  # noqa: BLE001
            if engine == "notetakers":
                raise
            print(f"  notetakers unavailable ({exc}); falling back to local", flush=True)
    if engine in ("faster-whisper", "auto", "whisper"):
        if not wav.exists():
            to_wav_16k(audio_path, wav)
        return transcribe_faster_whisper(wav, model_size=model_size), "faster-whisper"
    raise RuntimeError(f"unknown engine {engine}")


def load_stt_skip() -> set[str]:
    if not STT_SKIP_PATH.exists():
        return set()
    try:
        data = json.loads(STT_SKIP_PATH.read_text(encoding="utf-8"))
        return {str(x) for x in (data.get("keys") or [])}
    except Exception:  # noqa: BLE001
        return set()


def remember_stt_skip(podcast: str, episode: str, reason: str) -> None:
    key = f"{normalize(podcast)}|{normalize(episode)}"
    data = {"keys": [], "reasons": {}}
    if STT_SKIP_PATH.exists():
        try:
            data = json.loads(STT_SKIP_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    keys = list(data.get("keys") or [])
    if key not in keys:
        keys.append(key)
    reasons = dict(data.get("reasons") or {})
    reasons[key] = reason
    STT_SKIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    STT_SKIP_PATH.write_text(
        json.dumps({"keys": keys, "reasons": reasons}, indent=2) + "\n",
        encoding="utf-8",
    )


def pick_candidates(
    episodes: list[dict],
    conn,
    *,
    years: set[int],
    max_episodes: int,
    max_minutes: float,
) -> list[int]:
    # score: priority show rank, recency, shorter duration
    show_rank = {n: i for i, n in enumerate(PRIORITY_SHOWS)}
    counts = Counter(ep.get("p") for ep in episodes)
    skip = load_stt_skip()
    scored: list[tuple[float, int]] = []
    for i, ep in enumerate(episodes):
        y = int(ep.get("y") or 0)
        if years and y not in years:
            continue
        if already_good(conn, i, episodes):
            continue
        pod = ep.get("p") or ""
        if pod not in show_rank and counts[pod] < 200:
            continue
        skip_key = f"{normalize(pod)}|{normalize(ep.get('e') or '')}"
        if skip_key in skip:
            continue
        # skip if we already have any long-ish publisher text
        existing = get_full(
            conn, i, expect_podcast=pod, expect_episode=ep.get("e")
        )
        if existing and existing["src"] == "transcript" and existing["chars"] >= 1500:
            continue
        mins = dur_minutes(ep)
        if mins > 45:
            continue
        # Skip promos / trailers — Whisper on <3 min clips wastes budget.
        if mins < 3.0:
            continue
        rank = show_rank.get(pod, 50 + (0 if counts[pod] >= 500 else 20))
        score = rank * 1000 + (2030 - y) * 10 + mins
        scored.append((score, i))
    scored.sort()
    picked: list[int] = []
    budget = 0.0
    for _score, idx in scored:
        mins = dur_minutes(episodes[idx])
        if len(picked) >= max_episodes:
            break
        if budget + mins > max_minutes:
            continue
        picked.append(idx)
        budget += mins
    return picked


def load_episode_audio_urls() -> list[str]:
    """Pocket Casts export CSV includes direct Episode URL for every row."""
    import csv

    if not EPISODES_CSV.exists():
        return []
    with EPISODES_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [(r.get("Episode URL") or "").strip() for r in rows]


def resolve_audio(episodes: list[dict], idxs: list[int]) -> dict[int, str]:
    audio_for: dict[int, str] = {}
    csv_urls = load_episode_audio_urls()
    if csv_urls:
        for i in idxs:
            if i < len(csv_urls) and csv_urls[i].startswith("http"):
                audio_for[i] = csv_urls[i]
        print(f"  audio from episodes.csv: {len(audio_for)}/{len(idxs)}", flush=True)
        if len(audio_for) == len(idxs):
            return audio_for

    # Fallback: current RSS feed enclosures (recent episodes only)
    by_show: dict[str, list[int]] = defaultdict(list)
    for i in idxs:
        if i in audio_for:
            continue
        by_show[episodes[i].get("p") or ""].append(i)
    for show, show_idxs in by_show.items():
        if not show:
            continue
        print(f"  resolve audio map via RSS: {show}", flush=True)
        try:
            feed = itunes_feed(show)
            time.sleep(0.2)
            if not feed:
                continue
            amap = parse_audio_map(http_get(feed).decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            print(f"  feed fail {show}: {exc}", flush=True)
            continue
        for i in show_idxs:
            norm = normalize(episodes[i].get("e") or "")
            url = amap.get(norm)
            if not url and len(norm) >= 28:
                for k, v in amap.items():
                    if norm in k or k in norm:
                        url = v
                        break
            if url:
                audio_for[i] = url
    return audio_for


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-episodes", type=int, default=40)
    ap.add_argument("--max-minutes", type=float, default=480)  # 8 hours audio budget
    ap.add_argument("--years", default="2024,2025,2026")
    ap.add_argument("--model", default="base")
    ap.add_argument(
        "--engine",
        choices=("auto", "faster-whisper", "notetakers"),
        default="auto",
        help="auto: NoteTakers free quota then local faster-whisper",
    )
    ap.add_argument(
        "--notetakers-limit",
        type=int,
        default=10,
        help="Max free NoteTakers calls this run (API cap is 10/day/IP)",
    )
    args = ap.parse_args()
    years = {int(y) for y in args.years.split(",") if y.strip()}

    episodes = json.loads((TABLES / "episodes.json").read_text(encoding="utf-8"))
    conn = connect()
    candidates = pick_candidates(
        episodes,
        conn,
        years=years,
        max_episodes=args.max_episodes,
        max_minutes=args.max_minutes,
    )
    print(
        f"candidates={len(candidates)} years={sorted(years)} engine={args.engine}",
        flush=True,
    )
    audio_for = resolve_audio(episodes, candidates)
    print(f"audio_resolved={len(audio_for)}/{len(candidates)}", flush=True)

    ok = 0
    fail = 0
    by_engine: Counter = Counter()
    notetakers_left = [
        args.notetakers_limit if args.engine in ("auto", "notetakers") else 0
    ]
    with tempfile.TemporaryDirectory(prefix="stt-") as td:
        tdir = Path(td)
        for n, idx in enumerate(candidates, 1):
            url = audio_for.get(idx)
            if not url:
                print(f"[{n}/{len(candidates)}] skip no-audio idx={idx}", flush=True)
                continue
            ep = episodes[idx]
            print(
                f"[{n}/{len(candidates)}] STT {ep.get('p')} · {ep.get('e')[:60]}",
                flush=True,
            )
            raw = tdir / f"{idx}.audio"
            wav = tdir / f"{idx}.wav"
            try:
                if not audio_url_ok(url):
                    raise RuntimeError("audio URL preflight failed (404/empty)")
                download_audio(url, raw)
                # Prefer compact mp3/m4a for NoteTakers; wav for local Whisper.
                text, used = transcribe(
                    raw,
                    wav,
                    engine=args.engine,
                    model_size=args.model,
                    notetakers_left=notetakers_left,
                )
                if len(text) < 80:
                    raise RuntimeError(f"short transcript ({len(text)} chars)")
                wrote = upsert_full(
                    conn,
                    idx,
                    text,
                    src="stt",
                    podcast=ep.get("p"),
                    episode=ep.get("e"),
                    url=url,
                )
                conn.commit()
                if not wrote:
                    # Idx drift / trust-order skip — do not count as progress.
                    print(
                        f"  skip upsert (idx drift or lower-trust) chars={len(text)}",
                        flush=True,
                    )
                    continue
                ok += 1
                by_engine[used] += 1
                print(f"  ok via={used} chars={len(text)}", flush=True)
            except Exception as exc:  # noqa: BLE001
                fail += 1
                print(f"  FAIL {exc}", flush=True)
                err = str(exc)
                if "404" in err or "preflight failed" in err:
                    remember_stt_skip(
                        ep.get("p") or "", ep.get("e") or "", err[:200]
                    )
            finally:
                for p in (raw, wav):
                    try:
                        p.unlink(missing_ok=True)
                    except Exception:  # noqa: BLE001
                        pass

    meta = write_slim_notes(
        conn, TABLES / "notes.json", TABLES / "notes-meta.json", len(episodes)
    )
    print(
        json.dumps(
            {
                "stt_ok": ok,
                "stt_fail": fail,
                "by_engine": dict(by_engine),
                "coverage": {
                    k: meta.get(k)
                    for k in (
                        "withAnyText",
                        "withPublisherOrSttTranscript",
                        "withLongText2000plus",
                        "pctTranscript",
                        "pctLongText",
                    )
                },
            },
            indent=2,
        )
    )
    conn.close()


if __name__ == "__main__":
    main()
