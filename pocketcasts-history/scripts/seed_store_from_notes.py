#!/usr/bin/env python3
"""Seed transcripts/full.sqlite from existing slim notes.json (best-effort)."""

from __future__ import annotations

import json

from transcript_store import TABLES, connect, upsert_full, write_slim_notes


def main() -> None:
    episodes = json.loads((TABLES / "episodes.json").read_text(encoding="utf-8"))
    notes = json.loads((TABLES / "notes.json").read_text(encoding="utf-8"))
    conn = connect()
    n = 0
    for key, row in notes.items():
        try:
            idx = int(key)
        except ValueError:
            continue
        text = (row.get("text") or "").strip()
        if len(text) < 80:
            continue
        upsert_full(
            conn,
            idx,
            text,
            src=row.get("src") or "show-notes",
            podcast=row.get("p") or (episodes[idx].get("p") if idx < len(episodes) else None),
            episode=row.get("e") or (episodes[idx].get("e") if idx < len(episodes) else None),
            url=row.get("url"),
        )
        n += 1
    conn.commit()
    meta = write_slim_notes(
        conn, TABLES / "notes.json", TABLES / "notes-meta.json", len(episodes)
    )
    print(json.dumps({"seeded": n, "coverage": meta}, indent=2))
    conn.close()


if __name__ == "__main__":
    main()
