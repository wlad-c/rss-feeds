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


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
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
           OR (excluded.src IN ('transcript','stt') AND transcripts.src = 'show-notes')
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


def get_full(conn: sqlite3.Connection, episode_idx: int) -> dict | None:
    row = conn.execute(
        "SELECT episode_idx, podcast, episode, src, url, chars, text FROM transcripts WHERE episode_idx=?",
        (int(episode_idx),),
    ).fetchone()
    if not row:
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


def full_text_map(conn: sqlite3.Connection) -> dict[str, str]:
    """episode_idx(str) → full text for theme tagging."""
    out: dict[str, str] = {}
    for idx, text in conn.execute("SELECT episode_idx, text FROM transcripts"):
        out[str(idx)] = text
    return out


def coverage_stats(conn: sqlite3.Connection, total_episodes: int) -> dict:
    rows = conn.execute(
        "SELECT src, COUNT(*), SUM(chars) FROM transcripts GROUP BY src"
    ).fetchall()
    by_src = {src: {"count": n, "chars": int(chars or 0)} for src, n, chars in rows}
    n_full = conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0]
    n_transcriptish = conn.execute(
        "SELECT COUNT(*) FROM transcripts WHERE src IN ('transcript','stt')"
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
) -> dict:
    """Build Pages-friendly notes.json from the full store."""
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
