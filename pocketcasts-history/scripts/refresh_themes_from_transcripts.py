#!/usr/bin/env python3
"""Rebuild themes when the transcript store gains new full-text evidence.

Designed for hourly scheduling (GitHub Actions + Cursor timer):

  1. Fingerprint transcripts/full.sqlite (row counts, chars, max updated_at).
  2. Optionally adopt a newer store from a harvest branch (e.g. ongoing Gemini
     Xadrez Verbal harvest) when that branch has more youtube/transcript chars.
  3. If the fingerprint differs from tables/theme-refresh-stamp.json, rebuild
     themes (with within-episode time shares), sync docs/, rebuild standalone.
  4. Write a new stamp and exit 0. Exit 0 with "unchanged" when nothing to do.

Usage:
  python3 scripts/refresh_themes_from_transcripts.py
  python3 scripts/refresh_themes_from_transcripts.py \\
      --adopt-remote-branch cursor/xv-gemini-transcripts-8084
  python3 scripts/refresh_themes_from_transcripts.py --force
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
TABLES = ROOT / "tables"
TRANSCRIPTS = ROOT / "transcripts"
DB_PATH = TRANSCRIPTS / "full.sqlite"
STAMP_PATH = TABLES / "theme-refresh-stamp.json"
SCRIPTS = ROOT / "scripts"

ADOPT_FILES = [
    "pocketcasts-history/transcripts/full.sqlite",
    "pocketcasts-history/transcripts/coverage.json",
    "pocketcasts-history/tables/notes.json",
    "pocketcasts-history/tables/notes-meta.json",
]


def fingerprint(db_path: Path = DB_PATH) -> dict:
    if not db_path.exists():
        return {"missing": True}
    conn = sqlite3.connect(db_path)
    try:
        by_src = {
            src: {"count": int(n), "chars": int(chars or 0)}
            for src, n, chars in conn.execute(
                "SELECT src, COUNT(*), SUM(chars) FROM transcripts GROUP BY src"
            )
        }
        n, chars, updated = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(chars),0), MAX(updated_at) FROM transcripts"
        ).fetchone()
        # Stable digest of (idx, src, chars) — detects replacements even if totals match.
        rows = conn.execute(
            "SELECT episode_idx, src, chars FROM transcripts ORDER BY episode_idx"
        ).fetchall()
    finally:
        conn.close()
    h = hashlib.sha256()
    for idx, src, c in rows:
        h.update(f"{idx}|{src}|{c}\n".encode())
    return {
        "rows": int(n),
        "chars": int(chars or 0),
        "maxUpdatedAt": updated,
        "bySrc": by_src,
        "digest": h.hexdigest()[:24],
        "youtubeChars": int((by_src.get("youtube") or {}).get("chars") or 0),
        "transcriptishChars": int(
            (by_src.get("transcript") or {}).get("chars", 0)
            + (by_src.get("stt") or {}).get("chars", 0)
            + (by_src.get("youtube") or {}).get("chars", 0)
        ),
    }


def load_stamp() -> dict | None:
    if not STAMP_PATH.exists():
        return None
    try:
        return json.loads(STAMP_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def write_stamp(fp: dict, *, reason: str) -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    payload = {
        **fp,
        "refreshedAt": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
    }
    STAMP_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run(cmd: list[str], *, cwd: Path = ROOT) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=str(cwd))


def remote_branch_exists(branch: str) -> bool:
    r = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}"],
        cwd=str(REPO),
        capture_output=True,
    )
    if r.returncode == 0:
        return True
    subprocess.run(
        ["git", "fetch", "origin", branch, "--depth", "1"],
        cwd=str(REPO),
        capture_output=True,
    )
    r2 = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}"],
        cwd=str(REPO),
        capture_output=True,
    )
    return r2.returncode == 0


def adopt_remote_store(branch: str) -> bool:
    """Copy transcript store (+ notes) from origin/<branch> when richer than local."""
    if not remote_branch_exists(branch):
        print(f"adopt: origin/{branch} not found — skip", flush=True)
        return False
    ref = f"origin/{branch}"
    tmp = REPO / ".theme-refresh-tmp"
    tmp.mkdir(exist_ok=True)
    remote_db = tmp / "full.sqlite"
    try:
        with remote_db.open("wb") as out:
            subprocess.check_call(
                ["git", "show", f"{ref}:pocketcasts-history/transcripts/full.sqlite"],
                cwd=str(REPO),
                stdout=out,
            )
    except subprocess.CalledProcessError as exc:
        print(f"adopt: cannot read remote sqlite ({exc})", flush=True)
        return False

    local_fp = fingerprint(DB_PATH)
    remote_fp = fingerprint(remote_db)
    print(
        f"adopt: local youtubeChars={local_fp.get('youtubeChars')} "
        f"digest={local_fp.get('digest')} | remote youtubeChars="
        f"{remote_fp.get('youtubeChars')} digest={remote_fp.get('digest')}",
        flush=True,
    )
    remote_better = (
        remote_fp.get("transcriptishChars", 0) > local_fp.get("transcriptishChars", 0)
        or (
            remote_fp.get("transcriptishChars", 0)
            == local_fp.get("transcriptishChars", 0)
            and remote_fp.get("digest") != local_fp.get("digest")
            and (remote_fp.get("maxUpdatedAt") or "")
            > (local_fp.get("maxUpdatedAt") or "")
        )
    )
    if not remote_better:
        print("adopt: remote not richer — keep local store", flush=True)
        return False

    for rel in ADOPT_FILES:
        dest = REPO / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = subprocess.check_output(
                ["git", "show", f"{ref}:{rel}"], cwd=str(REPO)
            )
        except subprocess.CalledProcessError:
            print(f"adopt: skip missing {rel}", flush=True)
            continue
        dest.write_bytes(data)
        print(f"adopt: wrote {rel} ({len(data)} bytes)", flush=True)
    return True


def rebuild() -> None:
    run([sys.executable, str(SCRIPTS / "rebuild_theme_hierarchy.py")])
    run([sys.executable, str(SCRIPTS / "sync_docs_tables.py")], cwd=REPO)
    standalone = ROOT / "build-standalone.py"
    if standalone.exists():
        run([sys.executable, str(standalone)])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--adopt-remote-branch",
        default="",
        help="If set, pull a richer transcript store from origin/<branch> first.",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when the fingerprint matches the stamp.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print fingerprint / decide only; do not rebuild or write stamp.",
    )
    args = ap.parse_args()

    adopted = False
    if args.adopt_remote_branch:
        adopted = adopt_remote_store(args.adopt_remote_branch.strip())

    fp = fingerprint()
    stamp = load_stamp()
    same = (
        stamp is not None
        and stamp.get("digest") == fp.get("digest")
        and stamp.get("chars") == fp.get("chars")
    )
    print(json.dumps({"fingerprint": fp, "stampDigest": (stamp or {}).get("digest"), "same": same, "adopted": adopted}, indent=2))

    if same and not args.force and not adopted:
        print("unchanged — themes already match transcript store", flush=True)
        return 0

    if args.dry_run:
        print("dry-run — would rebuild themes", flush=True)
        return 0

    reason = "force" if args.force else ("adopted-remote" if adopted else "store-changed")
    rebuild()
    write_stamp(fp if not adopted else fingerprint(), reason=reason)
    print(f"refreshed themes ({reason})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
