"""File-based note store backed by Markdown files under data/notes/.

Layout:
  data/notes/
    <note-id>.md    — one file per research note

Each file is a self-contained Markdown document with YAML-like frontmatter.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


class NoteStore:
    """Persistent note store backed by individual Markdown files."""

    def __init__(self, base_dir: str | None = None) -> None:
        from pathlib import Path as _Path

        self.base_dir = _Path(
            base_dir or _Path(__file__).parent.parent.parent / "data" / "notes"
        ).resolve()
        self._ensure_dir()

    # ------------------------------------------------------------------
    # directory
    # ------------------------------------------------------------------

    def _ensure_dir(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # note id helpers
    # ------------------------------------------------------------------

    @staticmethod
    def slugify(text: str, max_len: int = 60) -> str:
        """Convert a title string into a safe filename slug."""
        import re

        slug = text.lower().strip()
        # remove URLs
        slug = re.sub(r"https?://\S+", "", slug)
        # keep only Chinese chars, alphanumeric, spaces, hyphens
        slug = re.sub(r"[^\w\s一-鿿-]", "", slug)
        # collapse whitespace
        slug = re.sub(r"\s+", "-", slug)
        # collapse hyphens
        slug = re.sub(r"-+", "-", slug)
        # trim
        slug = slug.strip("-")
        if len(slug) > max_len:
            slug = slug[:max_len].rstrip("-")
        return slug

    def _make_id(self, title_hint: str = "") -> str:
        """Generate a note id: <date>-<slug>."""
        date_part = self._now().strftime("%Y-%m-%d")
        if title_hint:
            slug = self.slugify(title_hint)
            if slug:
                return f"{date_part}-{slug}"
        unique = uuid.uuid4().hex[:8]
        return f"{date_part}-{unique}"

    def _note_path(self, note_id: str) -> Path:
        return self.base_dir / f"{note_id}.md"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def save(self, note) -> None:
        """Persist a ResearchNote to its markdown file."""
        from .types import ResearchNote

        if not note.id:
            note.id = self._make_id(note.summary[:40] if note.summary else "")
        note.updated_at = self._now()
        content = note.to_markdown()
        path = self._note_path(note.id)
        path.write_text(content, encoding="utf-8")

    def get(self, note_id: str) -> Optional["ResearchNote"]:
        """Load a single note by id. Returns None if not found."""
        from .types import ResearchNote

        path = self._note_path(note_id)
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        return ResearchNote.from_markdown(text)

    def list_all(
        self,
        status: str | None = None,
        topic: str | None = None,
        tag: str | None = None,
        limit: int = 50,
    ) -> list["ResearchNote"]:
        """List notes, optionally filtered by status/topic/tag, newest first."""
        from .types import ResearchNote

        paths = sorted(
            self.base_dir.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        results: list[ResearchNote] = []
        for p in paths:
            if len(results) >= limit:
                break
            text = p.read_text(encoding="utf-8")
            note = ResearchNote.from_markdown(text)
            if note is None:
                continue
            if status and note.status != status:
                continue
            if topic and note.topic != topic:
                continue
            if tag and tag not in note.tags:
                continue
            results.append(note)
        return results

    def delete(self, note_id: str) -> bool:
        """Delete a note file. Returns True if deleted, False if not found."""
        path = self._note_path(note_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def update_status(self, note_id: str, new_status: str) -> Optional["ResearchNote"]:
        """Promote/demote a note's status. Returns updated note or None."""
        note = self.get(note_id)
        if note is None:
            return None
        try:
            note.promote(new_status)
        except ValueError:
            return None
        self.save(note)
        return note
