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
    def norm(s):
        return " ".join((s or "").casefold().split())

    by_key = {
        (norm(ep.get("p")), norm(ep.get("e"))): i
        for i, ep in enumerate(episodes)
        if (ep.get("p") or "").strip() and (ep.get("e") or "").strip()
    }
    for key, row in notes.items():
        text = (row.get("text") or "").strip()
        if len(text) < 80:
            continue
        p = row.get("p")
        e = row.get("e")
        # Prefer podcast+title remap; never seed a mismatched idx from notes alone.
        match = by_key.get((norm(p), norm(e))) if p or e else None
        if match is None:
            try:
                idx = int(key)
            except ValueError:
                continue
            if not (0 <= idx < len(episodes)):
                continue
            # Only accept bare idx when note labels are absent or already match.
            ep = episodes[idx]
            if (p or e) and (
                norm(p) != norm(ep.get("p")) or norm(e) != norm(ep.get("e"))
            ):
                continue
            match = idx
            p = p or ep.get("p")
            e = e or ep.get("e")
        upsert_full(
            conn,
            match,
            text,
            src=row.get("src") or "show-notes",
            podcast=p,
            episode=e,
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
