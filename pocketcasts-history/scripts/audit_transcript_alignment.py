#!/usr/bin/env python3
"""Audit episode_idx alignment across transcript/notes/theme artifacts.

Fails with exit 1 if any labeled store row disagrees with episodes.json.
Run after sync, harvest, or theme rebuild.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "tables"
DB = ROOT / "transcripts" / "full.sqlite"
DOCS = ROOT.parent / "docs" / "tables"


def _norm(s: str | None) -> str:
    return " ".join((s or "").casefold().split())


def audit_pairs(name: str, episodes: list[dict], pairs: list[tuple[int, str | None, str | None]]) -> int:
    exact = poison = oob = nolabel = 0
    examples: list[dict] = []
    for idx, podcast, episode in pairs:
        if not (0 <= idx < len(episodes)):
            oob += 1
            poison += 1
            continue
        if not (podcast or "").strip() and not (episode or "").strip():
            nolabel += 1
            continue
        ep = episodes[idx]
        if _norm(ep.get("p")) == _norm(podcast) and _norm(ep.get("e")) == _norm(episode):
            exact += 1
        else:
            poison += 1
            if len(examples) < 5:
                examples.append(
                    {
                        "idx": idx,
                        "store": {"p": podcast, "e": episode},
                        "actual": {"p": ep.get("p"), "e": ep.get("e")},
                    }
                )
    print(
        f"{name}: exact={exact} poison={poison} oob={oob} "
        f"nolabel={nolabel} checked={exact + poison + nolabel}"
    )
    for ex in examples:
        print(f"  example={ex}")
    return poison


def main() -> None:
    episodes = json.loads((TABLES / "episodes.json").read_text(encoding="utf-8"))
    total_poison = 0

    if DB.exists():
        conn = sqlite3.connect(DB)
        pairs = [
            (int(i), p, e)
            for i, p, e in conn.execute(
                "SELECT episode_idx, podcast, episode FROM transcripts"
            )
        ]
        conn.close()
        total_poison += audit_pairs("full.sqlite", episodes, pairs)
    else:
        print("full.sqlite: missing")

    notes_path = TABLES / "notes.json"
    if notes_path.exists():
        notes = json.loads(notes_path.read_text(encoding="utf-8"))
        pairs = [
            (int(k), v.get("p"), v.get("e"))
            for k, v in notes.items()
            if str(k).isdigit() and isinstance(v, dict)
        ]
        total_poison += audit_pairs("tables/notes.json", episodes, pairs)

    docs_notes = DOCS / "notes.json"
    if docs_notes.exists():
        notes = json.loads(docs_notes.read_text(encoding="utf-8"))
        pairs = [
            (int(k), v.get("p"), v.get("e"))
            for k, v in notes.items()
            if str(k).isdigit() and isinstance(v, dict)
        ]
        total_poison += audit_pairs("docs/tables/notes.json", episodes, pairs)

    et_path = TABLES / "episode-themes.json"
    if et_path.exists():
        et = json.loads(et_path.read_text(encoding="utf-8"))
        if isinstance(et, list):
            ok = len(et) == len(episodes)
            print(
                f"episode-themes.json: list_len={len(et)} "
                f"episodes={len(episodes)} aligned_len={'yes' if ok else 'NO'}"
            )
            if not ok:
                total_poison += 1
        else:
            print(f"episode-themes.json: unexpected type {type(et).__name__}")

    print(f"TOTAL_POISON={total_poison}")
    if total_poison:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
