#!/usr/bin/env python3
"""Repair transcript store + notes.json after episode_idx drift.

Root cause: transcripts/notes were keyed only by episode_idx. When
episodes.json was rebuilt/reordered, every idx pointed at the wrong
episode (~100% poison). Content labels (podcast, episode title) on each
row remain correct — remapping by those labels restores alignment.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from transcript_store import (  # noqa: E402
    TABLES,
    connect,
    full_text_map,
    repair_episode_indices,
    write_slim_notes,
)


def main() -> None:
    episodes = json.loads((TABLES / "episodes.json").read_text(encoding="utf-8"))
    conn = connect()
    before = conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0]
    stats = repair_episode_indices(conn, episodes)
    aligned = full_text_map(conn, episodes)
    prior = {}
    if (TABLES / "notes.json").exists():
        prior = json.loads((TABLES / "notes.json").read_text(encoding="utf-8"))
    meta = write_slim_notes(
        conn,
        TABLES / "notes.json",
        TABLES / "notes-meta.json",
        total_episodes=len(episodes),
        preserve_notes=prior,
        episodes=episodes,
    )
    conn.close()
    print(f"before_rows={before}")
    print(f"repair={stats}")
    print(f"aligned_full_texts={len(aligned)}")
    print(f"notes_rewritten={meta.get('notesStored')}")
    # Verify zero poison
    poison = 0
    conn = connect()
    from transcript_store import assert_aligned

    try:
        stats = assert_aligned(conn, episodes)
        print(f"remaining_poison=0 exact={stats['exact']}")
    except RuntimeError as exc:
        print(exc)
        raise SystemExit(1) from exc
    finally:
        conn.close()


if __name__ == "__main__":
    main()
