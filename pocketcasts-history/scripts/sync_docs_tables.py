#!/usr/bin/env python3
"""Copy Pages-safe tables from pocketcasts-history/tables → docs/tables.

Does NOT copy transcripts/full.sqlite (too large for GitHub Pages).
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "pocketcasts-history" / "tables"
DST = ROOT / "docs" / "tables"

COPY = [
    "aggregates.json",
    "episodes.json",
    "episode-themes.json",
    "notes.json",
    "notes-meta.json",
    "podcasts.json",
    "themes.json",
]


def main() -> None:
    DST.mkdir(parents=True, exist_ok=True)
    for name in COPY:
        src = SRC / name
        if not src.exists():
            print(f"skip missing {name}")
            continue
        shutil.copy2(src, DST / name)
        print(f"copied {name} ({src.stat().st_size // 1024} KB)")
    # Also mirror transcript coverage summary into docs if present
    cov = ROOT / "pocketcasts-history" / "transcripts" / "coverage.json"
    if cov.exists():
        shutil.copy2(cov, DST / "transcript-coverage.json")
        print("copied transcript-coverage.json")


if __name__ == "__main__":
    main()
