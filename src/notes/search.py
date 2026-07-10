"""Note search via SQLite FTS5 — reuses MemoryDatabase for full-text indexing.

All notes are indexed on save. Search returns ranked results with snippets.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

from .types import ResearchNote


class NoteSearch:
    """Full-text search for research notes using SQLite FTS5."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        import sqlite3

        self.db_path = Path(
            db_path or Path(__file__).parent.parent.parent / "data" / "notes" / "notes.db"
        ).resolve()
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # connection
    # ------------------------------------------------------------------

    @property
    def conn(self):
        import sqlite3

        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # schema
    # ------------------------------------------------------------------

    def create_tables(self) -> None:
        cur = self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS notes (
                note_id     TEXT PRIMARY KEY,
                topic       TEXT NOT NULL DEFAULT '',
                tags        TEXT NOT NULL DEFAULT '',
                summary     TEXT NOT NULL DEFAULT '',
                key_points  TEXT NOT NULL DEFAULT '',
                full_discussion TEXT NOT NULL DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'discussion',
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                topic,
                tags,
                summary,
                key_points,
                full_discussion,
                content=notes,
                content_rowid=rowid
            );

            CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                INSERT INTO notes_fts(rowid, topic, tags, summary, key_points, full_discussion)
                VALUES (new.rowid, new.topic, new.tags, new.summary, new.key_points, new.full_discussion);
            END;

            CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, topic, tags, summary, key_points, full_discussion)
                VALUES ('delete', old.rowid, old.topic, old.tags, old.summary, old.key_points, old.full_discussion);
            END;

            CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, topic, tags, summary, key_points, full_discussion)
                VALUES ('delete', old.rowid, old.topic, old.tags, old.summary, old.key_points, old.full_discussion);
                INSERT INTO notes_fts(rowid, topic, tags, summary, key_points, full_discussion)
                VALUES (new.rowid, new.topic, new.tags, new.summary, new.key_points, new.full_discussion);
            END;
            """
        )
        cur.close()

    # ------------------------------------------------------------------
    # index
    # ------------------------------------------------------------------

    def index(self, note: ResearchNote) -> None:
        """Insert or update a note in the FTS index."""
        self.create_tables()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO notes
                (note_id, topic, tags, summary, key_points, full_discussion, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                note.id,
                note.topic,
                ", ".join(note.tags),
                note.summary,
                "\n".join(f"- {kp}" for kp in note.key_points),
                note.full_discussion,
                note.status,
                note.created_at.isoformat(),
                note.updated_at.isoformat(),
            ),
        )
        self.conn.commit()

    def index_all(self, notes: list[ResearchNote]) -> None:
        """Re-index all notes (rebuild from scratch)."""
        self.conn.execute("DELETE FROM notes")
        self.conn.commit()
        for note in notes:
            self.index(note)

    def remove(self, note_id: str) -> None:
        """Remove a note from the index."""
        self.create_tables()
        self.conn.execute("DELETE FROM notes WHERE note_id = ?", (note_id,))
        self.conn.commit()

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 20,
        status: str | None = None,
    ) -> list[dict]:
        """Keyword search over notes using LIKE (supports Chinese text).

        Returns list of dicts: {note_id, topic, tags, summary, key_points, rank, snippet}
        """
        import sqlite3

        self.create_tables()

        like = f"%{query}%"
        wheres = [
            "(summary LIKE ? OR full_discussion LIKE ? OR key_points LIKE ? OR tags LIKE ? OR topic LIKE ?)"
        ]
        params: list = [like, like, like, like, like]
        if status:
            wheres.append("status = ?")
            params.append(status)

        where_clause = " AND ".join(wheres)
        try:
            cur = self.conn.execute(
                f"""
                SELECT note_id, topic, tags, summary, key_points, full_discussion, status, created_at
                FROM notes
                WHERE {where_clause}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                params + [limit],
            )
            rows = cur.fetchall()
            cur.close()

            results = []
            for r in rows:
                # generate a snippet around the match
                snippet = self._snippet(r["summary"] + " " + r["full_discussion"], query)
                results.append({
                    "note_id": r["note_id"],
                    "topic": r["topic"],
                    "tags": r["tags"],
                    "summary": r["summary"],
                    "key_points": r["key_points"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "rank": 0.0,
                    "snippet": snippet,
                })
            return results
        except sqlite3.OperationalError:
            return []

    @staticmethod
    def _snippet(text: str, query: str, context: int = 30) -> str:
        """Extract a short snippet around the first occurrence of query."""
        idx = text.lower().find(query.lower())
        if idx < 0:
            return text[:80] + ("..." if len(text) > 80 else "")
        start = max(0, idx - context)
        end = min(len(text), idx + len(query) + context)
        snippet = text[start:end]
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(text) else ""
        return f"{prefix}{snippet}{suffix}"

    def search_simple(self, query: str, limit: int = 20) -> list[dict]:
        """Simple keyword search (LIKE fallback when FTS5 match fails)."""
        self.create_tables()
        like = f"%{query}%"
        cur = self.conn.execute(
            """
            SELECT note_id, topic, tags, summary, key_points, full_discussion, status, created_at
            FROM notes
            WHERE summary LIKE ? OR full_discussion LIKE ? OR key_points LIKE ? OR tags LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (like, like, like, like, limit),
        )
        rows = cur.fetchall()
        cur.close()
        return [
            {
                "note_id": r["note_id"],
                "topic": r["topic"],
                "tags": r["tags"],
                "summary": r["summary"],
                "key_points": r["key_points"],
                "status": r["status"],
                "created_at": r["created_at"],
                "rank": 0.0,
                "snippet": "",
            }
            for r in rows
        ]

    def count(self) -> int:
        """Return total indexed notes."""
        self.create_tables()
        cur = self.conn.execute("SELECT COUNT(*) FROM notes")
        row = cur.fetchone()
        cur.close()
        return row[0] if row else 0
