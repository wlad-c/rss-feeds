#!/usr/bin/env python3
"""Full-transcript store + slim Pages notes helpers.

Full text lives under pocketcasts-history/transcripts/ (not copied to docs/).
notes.json keeps searchable snippets + coverage flags for GitHub Pages.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "tables"
TRANSCRIPTS = ROOT / "transcripts"
DB_PATH = TRANSCRIPTS / "full.sqlite"
SNIPPET_CHARS = 900


def _norm(s: str | None) -> str:
    return " ".join((s or "").casefold().split())


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    # timeout helps when parallel harvest workers commit concurrently
    conn = sqlite3.connect(db_path, timeout=60)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=60000")
    except sqlite3.Error:
        pass
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS transcripts (
          episode_idx INTEGER PRIMARY KEY,
          podcast TEXT,
          episode TEXT,
          src TEXT NOT NULL,
          url TEXT,
          chars INTEGER NOT NULL,
          text TEXT NOT NULL,
          updated_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_transcripts_src ON transcripts(src)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_transcripts_podcast ON transcripts(podcast)"
    )
    conn.commit()
    return conn


def upsert_full(
    conn: sqlite3.Connection,
    episode_idx: int,
    text: str,
    *,
    src: str,
    podcast: str | None = None,
    episode: str | None = None,
    url: str | None = None,
) -> None:
    text = (text or "").strip()
    if len(text) < 80:
        return
    conn.execute(
        """
        INSERT INTO transcripts(episode_idx, podcast, episode, src, url, chars, text, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(episode_idx) DO UPDATE SET
          podcast=excluded.podcast,
          episode=excluded.episode,
          src=excluded.src,
          url=excluded.url,
          chars=excluded.chars,
          text=excluded.text,
          updated_at=datetime('now')
        WHERE excluded.chars >= transcripts.chars
           OR (
             excluded.src IN ('transcript', 'stt', 'youtube')
             AND transcripts.src = 'show-notes'
           )
        """,
        (
            int(episode_idx),
            podcast,
            episode,
            src,
            url,
            len(text),
            text,
        ),
    )


def get_full(
    conn: sqlite3.Connection,
    episode_idx: int,
    *,
    expect_podcast: str | None = None,
    expect_episode: str | None = None,
) -> dict | None:
    row = conn.execute(
        "SELECT episode_idx, podcast, episode, src, url, chars, text FROM transcripts WHERE episode_idx=?",
        (int(episode_idx),),
    ).fetchone()
    if not row:
        return None
    if expect_podcast is not None or expect_episode is not None:
        if _norm(row[1]) != _norm(expect_podcast) or _norm(row[2]) != _norm(
            expect_episode
        ):
            return None
    return {
        "i": row[0],
        "p": row[1],
        "e": row[2],
        "src": row[3],
        "url": row[4],
        "chars": row[5],
        "text": row[6],
    }


def assert_aligned(conn: sqlite3.Connection, episodes: list[dict]) -> dict:
    """Return alignment stats; raise if any row disagrees with episodes[idx]."""
    exact = poison = 0
    examples: list[dict] = []
    for idx, podcast, episode in conn.execute(
        "SELECT episode_idx, podcast, episode FROM transcripts"
    ):
        if not (0 <= int(idx) < len(episodes)):
            poison += 1
            continue
        ep = episodes[int(idx)]
        if _norm(ep.get("p")) == _norm(podcast) and _norm(ep.get("e")) == _norm(
            episode
        ):
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
    stats = {"exact": exact, "poison": poison, "examples": examples}
    if poison:
        raise RuntimeError(
            f"transcript index poison detected: {poison} bad / {exact} ok; "
            f"examples={examples}"
        )
    return stats


def full_text_map(
    conn: sqlite3.Connection,
    episodes: list[dict] | None = None,
) -> dict[str, str]:
    """episode_idx(str) → full text for theme tagging.

    If ``episodes`` is provided, only attach text when the stored podcast+episode
    labels match that index (or can be remapped by those labels). This guards
    against stale episode_idx after episodes.json was rebuilt/reordered.
    """
    rows = list(
        conn.execute(
            "SELECT episode_idx, podcast, episode, text FROM transcripts"
        )
    )
    if not episodes:
        return {str(idx): text for idx, _p, _e, text in rows if text}

    by_idx_ok: dict[str, str] = {}
    by_key: dict[tuple[str, str], str] = {}
    for idx, podcast, episode, text in rows:
        if not text:
            continue
        key = (_norm(podcast), _norm(episode))
        if key[0] and key[1]:
            # Prefer longer text if duplicate keys
            prev = by_key.get(key)
            if prev is None or len(text) > len(prev):
                by_key[key] = text
        if 0 <= int(idx) < len(episodes):
            ep = episodes[int(idx)]
            if _norm(ep.get("p")) == _norm(podcast) and _norm(ep.get("e")) == _norm(
                episode
            ):
                by_idx_ok[str(idx)] = text

    out: dict[str, str] = dict(by_idx_ok)
    for i, ep in enumerate(episodes):
        si = str(i)
        if si in out:
            continue
        key = (_norm(ep.get("p")), _norm(ep.get("e")))
        if key in by_key:
            out[si] = by_key[key]
    return out


def repair_episode_indices(
    conn: sqlite3.Connection, episodes: list[dict]
) -> dict:
    """Re-key transcript rows onto current episode indices by podcast+title.

    Orphan rows (no matching episode) are deleted so stale idx cannot poison tagging.
    """
    # O(1) lookup — nested scan was ~minutes on 8k×22k rows and invited drift bugs.
    by_key: dict[tuple[str, str], int] = {}
    for i, ep in enumerate(episodes):
        key = (_norm(ep.get("p")), _norm(ep.get("e")))
        if key[0] and key[1] and key not in by_key:
            by_key[key] = i

    rows = list(
        conn.execute(
            "SELECT episode_idx, podcast, episode, src, url, chars, text, updated_at "
            "FROM transcripts"
        )
    )
    target: dict[int, tuple] = {}
    orphans = 0
    collisions = 0
    for row in rows:
        _idx, podcast, episode, src, url, chars, text, updated_at = row
        key = (_norm(podcast), _norm(episode))
        match_i = by_key.get(key) if key[0] and key[1] else None
        if match_i is None:
            orphans += 1
            continue
        # Canonical labels from episodes.json (prevents case/whitespace drift)
        can_p = episodes[match_i].get("p") or podcast
        can_e = episodes[match_i].get("e") or episode
        prev = target.get(match_i)
        if prev is None or int(chars or 0) >= int(prev[5] or 0):
            if prev is not None:
                collisions += 1
            target[match_i] = (
                match_i,
                can_p,
                can_e,
                src,
                url,
                chars,
                text,
                updated_at,
            )
        else:
            collisions += 1

    conn.execute("DELETE FROM transcripts")
    conn.executemany(
        """
        INSERT INTO transcripts(episode_idx, podcast, episode, src, url, chars, text, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        list(target.values()),
    )
    conn.commit()
    return {
        "inputRows": len(rows),
        "kept": len(target),
        "orphansDeleted": orphans,
        "collisionsResolved": collisions,
    }


def coverage_stats(conn: sqlite3.Connection, total_episodes: int) -> dict:
    rows = conn.execute(
        "SELECT src, COUNT(*), SUM(chars) FROM transcripts GROUP BY src"
    ).fetchall()
    by_src = {src: {"count": n, "chars": int(chars or 0)} for src, n, chars in rows}
    n_full = conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0]
    n_transcriptish = conn.execute(
        "SELECT COUNT(*) FROM transcripts WHERE src IN ('transcript','stt','youtube')"
    ).fetchone()[0]
    long_n = conn.execute(
        "SELECT COUNT(*) FROM transcripts WHERE chars >= 2000"
    ).fetchone()[0]
    return {
        "totalEpisodes": total_episodes,
        "withAnyText": int(n_full),
        "withPublisherOrSttTranscript": int(n_transcriptish),
        "withLongText2000plus": int(long_n),
        "pctAnyText": round(100 * n_full / total_episodes, 2) if total_episodes else 0,
        "pctTranscript": round(100 * n_transcriptish / total_episodes, 2)
        if total_episodes
        else 0,
        "pctLongText": round(100 * long_n / total_episodes, 2) if total_episodes else 0,
        "bySrc": by_src,
    }


def snippet(text: str, limit: int = SNIPPET_CHARS) -> tuple[str, bool]:
    text = (text or "").strip()
    if len(text) <= limit:
        return text, False
    cut = text[:limit].rsplit(" ", 1)[0] or text[:limit]
    return cut.rstrip() + "…", True


def write_slim_notes(
    conn: sqlite3.Connection,
    notes_path: Path,
    meta_path: Path,
    total_episodes: int,
    *,
    preserve_notes: dict | None = None,
    episodes: list[dict] | None = None,
) -> dict:
    """Build Pages-friendly notes.json from the full store.

    When ``preserve_notes`` + ``episodes`` are given, keep prior note entries that
    are absent from sqlite but still label-aligned — so show-notes-only rows are
    not wiped by a transcript-index repair.
    """
    notes: dict[str, dict] = {}
    for idx, podcast, episode, src, url, chars, text in conn.execute(
        "SELECT episode_idx, podcast, episode, src, url, chars, text FROM transcripts"
    ):
        snip, truncated = snippet(text)
        notes[str(idx)] = {
            "src": src,
            "text": snip,
            "chars": int(chars),
            "full": bool(chars > SNIPPET_CHARS),
            "truncated": truncated,
            "url": url,
            "p": podcast,
            "e": episode,
        }
    if preserve_notes and episodes:
        by_key = {
            (_norm(ep.get("p")), _norm(ep.get("e"))): i
            for i, ep in enumerate(episodes)
            if (ep.get("p") or "").strip() and (ep.get("e") or "").strip()
        }
        for _k, row in preserve_notes.items():
            if not isinstance(row, dict):
                continue
            text = (row.get("text") or "").strip()
            if len(text) < 40:
                continue
            key = (_norm(row.get("p")), _norm(row.get("e")))
            match = by_key.get(key) if key[0] and key[1] else None
            if match is None:
                continue
            si = str(match)
            if si in notes:
                continue  # sqlite wins
            entry = dict(row)
            entry["p"] = episodes[match].get("p")
            entry["e"] = episodes[match].get("e")
            entry.setdefault("src", "show-notes")
            notes[si] = entry
    stats = coverage_stats(conn, total_episodes)
    notes_path.write_text(
        json.dumps(notes, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    meta = {
        **stats,
        "notesStored": len(notes),
        "snippetChars": SNIPPET_CHARS,
        "store": "transcripts/full.sqlite",
        "note": (
            "notes.json holds searchable snippets for Pages. "
            "Full text is in transcripts/full.sqlite (not shipped to docs/)."
        ),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (TRANSCRIPTS / "coverage.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta
