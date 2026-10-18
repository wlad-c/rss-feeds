#!/usr/bin/env python3
"""Harvest full YouTube transcripts via Gemini for one or more shows.

Replicates the Xadrez Verbal supervisor pattern (chunked Gemini + model
sharding + claim locks + periodic git commits) for arbitrary shows already
mapped in harvest_youtube_transcripts.YT_CHANNELS.

Usage:
  python3 scripts/gemini_show_supervisor.py --shows "The Daily" "O Assunto"
  python3 scripts/gemini_show_supervisor.py --shows "Sinica Podcast" --once
  python3 scripts/gemini_show_supervisor.py --shows "Foro de Teresina" \\
      --models gemini-2.5-flash-lite gemini-2.5-flash
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TABLES = ROOT / "tables"
DB = ROOT / "transcripts" / "full.sqlite"
LOG_DIR = Path("/tmp/gemini-show-supervisor")

# Prefer models NOT used by the live XV supervisor (3.5-flash-lite / 3.6-flash /
# 3.1-flash-lite) so free-tier per-model RPD does not collide. Only include
# models that accept YouTube fileData + videoMetadata (2.5-* return 404).
DEFAULT_MODELS = [
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-flash-lite-latest",
]


def remaining(shows: list[str], min_year: int = 2022) -> tuple[int, int]:
    show_set = set(shows)
    episodes = json.loads((TABLES / "episodes.json").read_text(encoding="utf-8"))
    con = sqlite3.connect(DB)
    have = {
        r[0]
        for r in con.execute(
            "SELECT episode_idx FROM transcripts WHERE src='youtube'"
        )
    }
    # Also treat long publisher/stt transcripts as already covered
    have |= {
        r[0]
        for r in con.execute(
            "SELECT episode_idx FROM transcripts "
            "WHERE src IN ('transcript','stt') AND length(text) >= 2000"
        )
    }
    con.close()
    total = 0
    need = 0
    for i, ep in enumerate(episodes):
        if (ep.get("p") or "") not in show_set:
            continue
        y = int(ep.get("y") or 0)
        if y and y < min_year:
            continue
        total += 1
        if i not in have:
            need += 1
    return need, total


def remaining_by_show(shows: list[str], min_year: int = 2022) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for s in shows:
        out[s] = remaining([s], min_year)
    return out


def probe_model(model: str, key: str) -> tuple[bool, float | None]:
    """Return (ok, retry_seconds_if_daily_blocked)."""
    body = {
        "contents": [
            {
                "parts": [
                    {"text": "ok"},
                    {
                        "file_data": {
                            "file_uri": "https://www.youtube.com/watch?v=jNQXAC9IVRw"
                        },
                        "video_metadata": {
                            "start_offset": "0s",
                            "end_offset": "15s",
                        },
                    },
                ]
            }
        ],
        "generationConfig": {
            "mediaResolution": "MEDIA_RESOLUTION_LOW",
            "maxOutputTokens": 8,
        },
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            resp.read()
        return True, None
    except urllib.error.HTTPError as exc:
        msg = exc.read().decode("utf-8", errors="replace")
        if exc.code != 429:
            print(f"  probe {model}: HTTP {exc.code} {msg[:160]}", flush=True)
            return False, None
        m = re.search(
            r"retry in\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+(?:\.\d+)?)\s*s)?",
            msg,
            re.I,
        )
        retry = 0.0
        if m:
            retry = (
                int(m.group(1) or 0) * 3600
                + int(m.group(2) or 0) * 60
                + float(m.group(3) or 0)
            )
        if retry >= 3600 or "PerDay" in msg:
            print(f"  probe {model}: daily blocked ~{retry:.0f}s", flush=True)
            return False, retry or 3600
        print(f"  probe {model}: soft 429 ~{retry:.0f}s — treating as usable", flush=True)
        return True, retry
    except Exception as exc:  # noqa: BLE001
        print(f"  probe {model}: {exc}", flush=True)
        return False, None


def run_worker(
    model: str,
    show: str,
    max_eps: int,
    parallel: int,
    min_year: int,
    channel_limit: int,
) -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    safe_show = re.sub(r"[^\w]+", "_", show).strip("_")[:40]
    log = LOG_DIR / f"w-{safe_show}-{model.replace('.', '_')}.log"
    cmd = [
        sys.executable,
        str(SCRIPTS / "harvest_youtube_transcripts.py"),
        "--shows",
        show,
        "--backends",
        "gemini",
        "--max-episodes",
        str(max_eps),
        "--min-year",
        str(min_year),
        "--max-minutes",
        "0",
        "--channel-limit",
        str(channel_limit),
        "--sleep",
        "2",
        "--no-search-fallback",
        "--gemini-model",
        model,
        "--gemini-parallel",
        str(parallel),
    ]
    env = os.environ.copy()
    env["PATH"] = f"{Path.home() / '.local/bin'}:{env.get('PATH', '')}"
    fh = open(log, "a", encoding="utf-8")
    fh.write(f"\n\n===== wave start {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    fh.flush()
    print(f"  spawn {show!r} @ {model} → {log}", flush=True)
    return subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=fh, stderr=subprocess.STDOUT)


def git_commit_progress(shows: list[str], min_year: int) -> None:
    """Best-effort commit of sqlite + notes if dirty."""
    try:
        subprocess.run(
            [
                "git",
                "add",
                "pocketcasts-history/transcripts/full.sqlite",
                "pocketcasts-history/transcripts/coverage.json",
                "pocketcasts-history/tables/notes.json",
                "pocketcasts-history/tables/notes-meta.json",
                "pocketcasts-history/tables/youtube-harvest.json",
                "pocketcasts-history/scripts/harvest_youtube_transcripts.py",
                "pocketcasts-history/scripts/gemini_show_supervisor.py",
                "pocketcasts-history/scripts/xv_gemini_supervisor.py",
                "pocketcasts-history/scripts/transcript_store.py",
                ".gitignore",
            ],
            cwd="/workspace",
            check=False,
            capture_output=True,
        )
        st = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd="/workspace",
            capture_output=True,
            text=True,
        )
        if not st.stdout.strip():
            return
        need, total = remaining(shows, min_year)
        have = total - need
        label = shows[0] if len(shows) == 1 else f"{len(shows)}-shows"
        msg = f"Gemini YT harvest ({label}): {have}/{total} covered (need {need})"
        subprocess.run(["git", "commit", "-m", msg], cwd="/workspace", check=False)
        subprocess.run(
            ["git", "push", "-u", "origin", "HEAD"],
            cwd="/workspace",
            check=False,
        )
        print(f"  committed/pushed: {msg}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"  commit skip: {exc}", flush=True)


def assign_show_model_pairs(
    shows: list[str],
    models: list[str],
    min_year: int,
) -> list[tuple[str, str]]:
    """Pair each usable model with the show that still has the largest gap."""
    by = remaining_by_show(shows, min_year)
    # Sort shows by remaining desc so biggest gaps get models first
    ranked = sorted(shows, key=lambda s: by[s][0], reverse=True)
    ranked = [s for s in ranked if by[s][0] > 0]
    if not ranked:
        return []
    pairs: list[tuple[str, str]] = []
    for i, model in enumerate(models):
        show = ranked[i % len(ranked)]
        pairs.append((show, model))
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--shows",
        nargs="+",
        required=True,
        help="Podcast names as in episodes.json / YT_CHANNELS",
    )
    ap.add_argument(
        "--models",
        nargs="*",
        default=None,
        help="Gemini models to shard across (default: non-XV free-tier set)",
    )
    ap.add_argument("--min-year", type=int, default=2022)
    ap.add_argument("--max-episodes-per-wave", type=int, default=8)
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--channel-limit", type=int, default=500)
    ap.add_argument("--once", action="store_true", help="Single wave then exit")
    ap.add_argument("--no-commit", action="store_true")
    args = ap.parse_args()

    models = args.models or DEFAULT_MODELS
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY unset")

    # Ensure yt-dlp on PATH for child processes
    local_bin = str(Path.home() / ".local/bin")
    os.environ["PATH"] = f"{local_bin}:{os.environ.get('PATH', '')}"

    wave = 0
    while True:
        wave += 1
        need, total = remaining(args.shows, args.min_year)
        by = remaining_by_show(args.shows, args.min_year)
        print(
            f"\n=== wave {wave} need={need}/{total} "
            f"({time.strftime('%H:%M:%S')}) ===",
            flush=True,
        )
        for s, (n, t) in by.items():
            print(f"  {s}: need {n}/{t}", flush=True)
        if need <= 0:
            print("BACKLOG CLEAR — all target shows covered", flush=True)
            if not args.no_commit:
                git_commit_progress(args.shows, args.min_year)
            return

        usable: list[str] = []
        daily_waits: list[float] = []
        for model in models:
            ok, retry = probe_model(model, key)
            if ok:
                usable.append(model)
            elif retry:
                daily_waits.append(retry)
            time.sleep(0.5)

        if not usable:
            wait = min(daily_waits) if daily_waits else 1800
            wait = max(120.0, min(wait, 6 * 3600))
            print(f"all models daily-blocked; sleeping {wait:.0f}s", flush=True)
            if args.once:
                return
            time.sleep(wait)
            continue

        pairs = assign_show_model_pairs(args.shows, usable, args.min_year)
        if not pairs:
            print("no remaining shows to assign", flush=True)
            return

        procs = [
            run_worker(
                model,
                show,
                args.max_episodes_per_wave,
                args.parallel,
                args.min_year,
                args.channel_limit,
            )
            for show, model in pairs
        ]
        for p in procs:
            p.wait()
        print(
            f"  wave {wave} workers done: "
            + ", ".join(f"rc={p.returncode}" for p in procs),
            flush=True,
        )
        if not args.no_commit:
            try:
                con = sqlite3.connect(DB)
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                con.close()
            except sqlite3.Error:
                pass
            git_commit_progress(args.shows, args.min_year)

        need2, _ = remaining(args.shows, args.min_year)
        print(f"  after wave: need={need2}", flush=True)
        if args.once:
            return
        if need2 >= need:
            print("  no progress this wave; cooling 180s", flush=True)
            time.sleep(180)
        else:
            time.sleep(15)


if __name__ == "__main__":
    main()
