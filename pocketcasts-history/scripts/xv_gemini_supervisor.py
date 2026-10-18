#!/usr/bin/env python3
"""Keep harvesting Xadrez Verbal YouTube transcripts via Gemini until done.

Spawns model-sharded workers with parallel chunk fetches. Soft-retries RPM
429s inside the harvest script; this supervisor sleeps on true daily quotas
and exits only when the backlog is cleared (or --once).

Usage:
  python3 scripts/xv_gemini_supervisor.py
  python3 scripts/xv_gemini_supervisor.py --max-episodes-per-wave 8 --parallel 2
"""

from __future__ import annotations

import argparse
import json
import os
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
LOG_DIR = Path("/tmp/xv-supervisor")

# Free-tier RPD is per model — shard across every flash/lite that accepts
# YouTube videoMetadata windows.
MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-flash-lite-latest",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-flash-latest",
    "gemini-3-flash-preview",
]


def remaining(min_year: int = 2022) -> tuple[int, int]:
    episodes = json.loads((TABLES / "episodes.json").read_text(encoding="utf-8"))
    con = sqlite3.connect(DB)
    have = {
        r[0]
        for r in con.execute(
            "SELECT episode_idx FROM transcripts "
            "WHERE podcast LIKE '%Xadrez%' AND src='youtube'"
        )
    }
    con.close()
    total = 0
    need = 0
    for i, ep in enumerate(episodes):
        if (ep.get("p") or "") != "Xadrez Verbal":
            continue
        y = int(ep.get("y") or 0)
        if y and y < min_year:
            continue
        total += 1
        if i not in have:
            need += 1
    return need, total


def probe_model(model: str, key: str) -> tuple[bool, float | None]:
    """Return (ok, retry_seconds_if_daily_blocked)."""
    body = {
        "contents": [
            {
                "parts": [
                    {"text": "ok"},
                    {
                        "file_data": {
                            "file_uri": "https://www.youtube.com/watch?v=A8i6JWhQpLc"
                        },
                        "video_metadata": {
                            "start_offset": "0s",
                            "end_offset": "20s",
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
        if exc.code == 402 or "prepayment credits are depleted" in msg.lower():
            # Paid project, but prepaid balance is $0 — not a free-tier choice.
            print(
                f"  probe {model}: PREPAY CREDITS DEPLETED (402) — top up at "
                f"https://ai.studio/projects",
                flush=True,
            )
            return False, 1800.0
        if exc.code != 429:
            print(f"  probe {model}: HTTP {exc.code} {msg[:160]}", flush=True)
            return False, None
        m = __import__("re").search(
            r"retry in\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+(?:\.\d+)?)\s*s)?",
            msg,
            __import__("re").I,
        )
        retry = 0.0
        if m:
            retry = (
                int(m.group(1) or 0) * 3600
                + int(m.group(2) or 0) * 60
                + float(m.group(3) or 0)
            )
        # Any FreeTier / PerDay signal → not usable, even if retry is short.
        if (
            retry >= 600
            or "PerDay" in msg
            or "free_tier" in msg.lower()
            or "FreeTier" in msg
        ):
            print(f"  probe {model}: FreeTier quota blocked ~{retry:.0f}s", flush=True)
            return False, retry or 3600
        print(f"  probe {model}: soft 429 ~{retry:.0f}s — treating as usable", flush=True)
        return True, retry
    except Exception as exc:  # noqa: BLE001
        print(f"  probe {model}: {exc}", flush=True)
        return False, None


def run_worker(
    model: str,
    max_eps: int,
    parallel: int,
    min_year: int,
    *,
    channel_limit: int = 2000,
    search_fallback: bool = True,
) -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / f"w-{model.replace('.', '_')}.log"
    cmd = [
        sys.executable,
        str(SCRIPTS / "harvest_youtube_transcripts.py"),
        "--shows",
        "Xadrez Verbal",
        "--backends",
        "gemini",
        "--max-episodes",
        str(max_eps),
        "--min-year",
        str(min_year),
        "--max-minutes",
        "0",
        "--sleep",
        "2",
        "--channel-limit",
        str(channel_limit),
        "--gemini-model",
        model,
        "--gemini-parallel",
        str(parallel),
    ]
    # Search fallback needed for episodes older than the uploads window /
    # imperfect title matches — required to drain the full backlog.
    if not search_fallback:
        cmd.append("--no-search-fallback")
    env = os.environ.copy()
    env["PATH"] = f"{Path.home() / '.local/bin'}:{env.get('PATH', '')}"
    fh = open(log, "a", encoding="utf-8")
    fh.write(f"\n\n===== wave start {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    fh.flush()
    print(f"  spawn {model} → {log}", flush=True)
    return subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=fh, stderr=subprocess.STDOUT)


def git_commit_progress() -> None:
    """Best-effort commit of sqlite + notes if dirty."""
    try:
        subprocess.run(
            ["git", "add",
             "pocketcasts-history/transcripts/full.sqlite",
             "pocketcasts-history/transcripts/coverage.json",
             "pocketcasts-history/tables/notes.json",
             "pocketcasts-history/tables/notes-meta.json",
             "pocketcasts-history/tables/youtube-harvest.json",
             "pocketcasts-history/scripts/harvest_youtube_transcripts.py",
             "pocketcasts-history/scripts/xv_gemini_supervisor.py",
             "pocketcasts-history/scripts/transcript_store.py"],
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
        need, total = remaining()
        have = total - need
        msg = f"XV Gemini harvest progress: {have}/{total} youtube (need {need})"
        subprocess.run(["git", "commit", "-m", msg], cwd="/workspace", check=False)
        subprocess.run(
            ["git", "push", "-u", "origin", "HEAD"],
            cwd="/workspace",
            check=False,
        )
        print(f"  committed/pushed: {msg}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"  commit skip: {exc}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-year", type=int, default=2022)
    ap.add_argument("--max-episodes-per-wave", type=int, default=10)
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--once", action="store_true", help="Single wave then exit")
    ap.add_argument("--commit-every-wave", action="store_true", default=True)
    args = ap.parse_args()

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY unset")

    wave = 0
    while True:
        wave += 1
        need, total = remaining(args.min_year)
        print(
            f"\n=== wave {wave} need={need}/{total} "
            f"({time.strftime('%H:%M:%S')}) ===",
            flush=True,
        )
        if need <= 0:
            print("BACKLOG CLEAR — all XV episodes have src=youtube", flush=True)
            git_commit_progress()
            return

        usable: list[str] = []
        daily_waits: list[float] = []
        for model in MODELS:
            ok, retry = probe_model(model, key)
            if ok:
                usable.append(model)
            elif retry:
                daily_waits.append(retry)
            time.sleep(1)

        if not usable:
            # Re-probe often: if the project is upgraded Free→Paid mid-run,
            # we should resume within minutes instead of sleeping for hours.
            wait = float(os.environ.get("GEMINI_QUOTA_REPROBE_SECS", "900"))
            wait = max(120.0, min(wait, 1800.0))
            hint = min(daily_waits) if daily_waits else None
            print(
                f"all models quota-blocked"
                + (f" (server retry≈{hint:.0f}s)" if hint else "")
                + f"; re-probing in {wait:.0f}s",
                flush=True,
            )
            if args.once:
                return
            time.sleep(wait)
            continue

        print(f"  usable models ({len(usable)}): {', '.join(usable)}", flush=True)
        procs = [
            run_worker(m, args.max_episodes_per_wave, args.parallel, args.min_year)
            for m in usable
        ]
        for p in procs:
            p.wait()
        print(
            f"  wave {wave} workers done: "
            + ", ".join(f"rc={p.returncode}" for p in procs),
            flush=True,
        )
        if args.commit_every_wave:
            # checkpoint WAL into main db file before commit
            try:
                con = sqlite3.connect(DB)
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                con.close()
            except sqlite3.Error:
                pass
            git_commit_progress()

        need2, _ = remaining(args.min_year)
        print(f"  after wave: need={need2}", flush=True)
        if args.once:
            return
        if need2 >= need:
            # no progress (often mid-wave FreeTier exhaust) — re-probe soon
            # so a Paid-tier flip is picked up quickly.
            wait = float(os.environ.get("GEMINI_QUOTA_REPROBE_SECS", "900"))
            wait = max(120.0, min(wait, 1800.0))
            print(
                f"  no progress this wave; re-probing in {wait:.0f}s",
                flush=True,
            )
            time.sleep(wait)
        else:
            time.sleep(15)


if __name__ == "__main__":
    main()
