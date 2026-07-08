"""File-based memory store using markdown files.

Layout (under base_dir):
  MEMORY.md          - overview / index
  YYYY-MM-DD.md      - daily memory entries in plain markdown
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from .types import MemoryEntry


class MemoryStore:
    """Persistent memory store backed by daily markdown files."""

    def __init__(self, base_dir: str | None = None) -> None:
        self.base_dir = Path(base_dir or Path.home() / ".baize" / "memory")
        self.ensure_dir()

    # ------------------------------------------------------------------
    # directory setup
    # ------------------------------------------------------------------

    def ensure_dir(self) -> None:
        """Create base_dir and stub MEMORY.md if missing."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        memory_md = self.base_dir / "MEMORY.md"
        if not memory_md.exists():
            memory_md.write_text(
                "# Baize Memory Store\n\nPersistent memory backed by daily markdown files.\n"
            )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _daily_path(base: Path, dt: datetime | None = None) -> Path:
        dt = dt or datetime.now(timezone.utc)
        return base / f"{dt.strftime('%Y-%m-%d')}.md"

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _entry_to_md(entry: MemoryEntry) -> str:
        """Serialize a MemoryEntry to a markdown block."""
        lines = [
            f"## {entry.id}",
            f"- **source**: {entry.source}",
            f"- **created**: {entry.created_at.isoformat()}",
            f"- **updated**: {entry.updated_at.isoformat()}",
        ]
        if entry.metadata:
            lines.append(f"- **metadata**: {entry.metadata}")
        lines.append("")
        lines.append(entry.content)
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _parse_entries(text: str) -> List[MemoryEntry]:
        """Parse a markdown file into MemoryEntry list."""
        entries: List[MemoryEntry] = []
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("## "):
                entry_id = line[3:].strip()
                i += 1
                source = ""
                created_at = None
                updated_at = None
                metadata: dict = {}
                content_lines: List[str] = []
                # read header block (lines starting with - **)
                while i < len(lines) and lines[i].startswith("- **"):
                    hdr = lines[i]
                    if hdr.startswith("- **source**"):
                        source = hdr.split(":", 1)[1].strip()
                    elif hdr.startswith("- **created**"):
                        created_at = datetime.fromisoformat(
                            hdr.split(":", 1)[1].strip()
                        )
                    elif hdr.startswith("- **updated**"):
                        updated_at = datetime.fromisoformat(
                            hdr.split(":", 1)[1].strip()
                        )
                    elif hdr.startswith("- **metadata**"):
                        import ast

                        try:
                            metadata = ast.literal_eval(
                                hdr.split(":", 1)[1].strip()
                            )
                        except Exception:
                            metadata = {}
                    i += 1
                # skip blank line after header
                if i < len(lines) and lines[i] == "":
                    i += 1
                # read content until next ## or EOF
                while i < len(lines) and not lines[i].startswith("## "):
                    content_lines.append(lines[i])
                    i += 1
                content = "\n".join(content_lines).strip()
                if content and source and created_at:
                    entries.append(
                        MemoryEntry(
                            id=entry_id,
                            content=content,
                            source=source,
                            created_at=created_at,
                            updated_at=updated_at or created_at,
                            metadata=metadata,
                        )
                    )
            else:
                i += 1
        return entries

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def append(self, entry: MemoryEntry) -> None:
        """Append an entry to the daily file."""
        daily = self._daily_path(self.base_dir, entry.created_at)
        md_block = self._entry_to_md(entry)
        with open(daily, "a", encoding="utf-8") as f:
            f.write(md_block + "\n")

    def get_recent(self, days: int = 7) -> List[MemoryEntry]:
        """Return entries from the last *days* daily files."""
        cutoff = self._now() - timedelta(days=days)
        entries: List[MemoryEntry] = []
        for p in sorted(self.base_dir.glob("????-??-??.md"), reverse=True):
            # parse date from filename
            try:
                file_date = datetime.strptime(p.stem, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue
            if file_date < cutoff:
                break
            text = p.read_text(encoding="utf-8")
            entries.extend(self._parse_entries(text))
        return entries

    def get_all(self) -> List[MemoryEntry]:
        """Return all entries from all daily files."""
        entries: List[MemoryEntry] = []
        for p in sorted(self.glob("????-??-??.md")):
            text = p.read_text(encoding="utf-8")
            entries.extend(self._parse_entries(text))
        return entries

    def glob(self, pattern: str) -> List[Path]:
        """Glob relative to base_dir."""
        return list(self.base_dir.glob(pattern))
