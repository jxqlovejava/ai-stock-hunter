"""SQLite-backed memory database with FTS5 full-text search.

Tables:
  chunks          - (chunk_id TEXT PK, content TEXT, metadata_json TEXT, created_at TEXT)
  chunks_fts      - FTS5 virtual table on (content) with content=chunks
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import List, Tuple


class MemoryDatabase:
    """Persistent SQLite store with FTS5 full-text search."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(
            db_path or Path.home() / ".baize" / "memory" / "memory.db"
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # connection management
    # ------------------------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # schema
    # ------------------------------------------------------------------

    def create_tables(self) -> None:
        """Create chunks + chunks_fts tables if they do not exist."""
        cur = self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id    TEXT PRIMARY KEY,
                content     TEXT NOT NULL,
                metadata_json TEXT DEFAULT '{}',
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                content,
                content=chunks,
                content_rowid=rowid
            );

            -- triggers to keep FTS in sync
            CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid, content)
                VALUES (new.rowid, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, content)
                VALUES ('delete', old.rowid, old.content);
            END;

            CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, content)
                VALUES ('delete', old.rowid, old.content);
                INSERT INTO chunks_fts(rowid, content)
                VALUES (new.rowid, new.content);
            END;
            """
        )
        cur.close()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def insert(
        self, chunk_id: str, content: str, metadata_json: str | dict = ""
    ) -> None:
        """Insert a chunk into the database.

        metadata_json can be a dict (auto-serialized) or a pre-serialized str.
        """
        if isinstance(metadata_json, dict):
            metadata_json = json.dumps(metadata_json, ensure_ascii=False)
        self.conn.execute(
            "INSERT OR REPLACE INTO chunks (chunk_id, content, metadata_json) "
            "VALUES (?, ?, ?)",
            (chunk_id, content, metadata_json),
        )
        self.conn.commit()

    def search(
        self, query: str, limit: int = 10
    ) -> List[Tuple[str, str, float]]:
        """Full-text search returning (chunk_id, content, bm25_score).

        Lower BM25 score = better match.  Sorted best-first.
        """
        try:
            cur = self.conn.execute(
                """
                SELECT c.chunk_id, c.content, rank
                FROM chunks_fts
                JOIN chunks ON chunks.rowid = chunks_fts.rowid
                WHERE chunks_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            )
            rows = cur.fetchall()
            cur.close()
            return [(r["chunk_id"], r["content"], float(r["rank"])) for r in rows]
        except sqlite3.OperationalError:
            # FTS5 match syntax error or empty query
            return []

    def count(self) -> int:
        """Return total number of chunks."""
        cur = self.conn.execute("SELECT COUNT(*) FROM chunks")
        row = cur.fetchone()
        cur.close()
        return row[0] if row else 0
