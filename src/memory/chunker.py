"""Markdown-aware content chunker.

Splits markdown text into segments suitable for embedding + indexing.
Preserves code blocks and splits at semantic boundaries (## headings).
"""

from __future__ import annotations

import re
from typing import List


class MarkdownChunker:
    """Split markdown into chunks, respecting structure."""

    def __init__(self, max_chunk_size: int = 500) -> None:
        self.max_chunk_size = max_chunk_size

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def chunk(self, content: str, max_chunk_size: int | None = None) -> List[str]:
        """Split *content* into a list of chunk strings.

        Strategy (in order of preference):
          1. Split on ## headings (top-level sections).
          2. If no headings, split on paragraphs (double newline).
          3. If any chunk exceeds *max_chunk_size*, recursively split by
             single newline, then by sentence boundary.

        Code blocks (```...```) are always kept intact.
        """
        max_sz = max_chunk_size or self.max_chunk_size
        if not content.strip():
            return []

        # Strategy 1: split by ## headings
        sections = self._split_by_headings(content)
        if len(sections) > 1:
            return self._cap_size(sections, max_sz)

        # Strategy 2: split by blank-line paragraphs
        paragraphs = [
            p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()
        ]
        if len(paragraphs) > 1:
            return self._cap_size(paragraphs, max_sz)

        # Strategy 3: split by single newline  (single paragraph)
        lines = [l for l in content.splitlines() if l.strip()]
        return self._cap_size(lines, max_sz)

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_by_headings(content: str) -> List[str]:
        """Split on lines starting with '## ' (level-2 headings).

        Returns the text *including* the heading line.
        """
        sections: List[str] = []
        current: List[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("## ") and not stripped.startswith("###"):
                if current:
                    sections.append("\n".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            sections.append("\n".join(current))
        return sections

    @staticmethod
    def _protect_code_blocks(chunks: List[str]) -> List[str]:
        """Reassemble chunks that would break a code block."""
        result: List[str] = []
        buffer: List[str] = []
        in_block = False
        for chunk in chunks:
            lines = chunk.splitlines()
            code_fence = sum(1 for l in lines if l.strip().startswith("```"))
            if code_fence % 2 == 0:
                # balanced fence within this chunk -- fine
                if in_block:
                    buffer.append(chunk)
                    result.append("\n".join(buffer))
                    buffer = []
                    in_block = False
                else:
                    result.append(chunk)
            else:
                # unbalanced fence -- toggle
                if in_block:
                    buffer.append(chunk)
                    result.append("\n".join(buffer))
                    buffer = []
                    in_block = False
                else:
                    in_block = True
                    buffer.append(chunk)
        if buffer:
            result.append("\n".join(buffer))
        return result

    def _cap_size(
        self, segments: List[str], max_sz: int
    ) -> List[str]:
        """Merge small segments and split large ones to respect max_sz."""
        if not segments:
            return []

        merged = self._merge_small(segments, max_sz)
        result: List[str] = []
        for seg in merged:
            if len(seg) <= max_sz:
                result.append(seg)
            else:
                result.extend(self._split_long(seg, max_sz))
        return self._protect_code_blocks(result)

    @staticmethod
    def _merge_small(segments: List[str], max_sz: int) -> List[str]:
        """Greedily merge adjacent small segments."""
        result: List[str] = []
        buffer = ""
        for seg in segments:
            if not buffer:
                buffer = seg
            elif len(buffer) + len(seg) < max_sz:
                buffer += "\n\n" + seg
            else:
                result.append(buffer)
                buffer = seg
        if buffer:
            result.append(buffer)
        return result

    @staticmethod
    def _split_long(text: str, max_sz: int) -> List[str]:
        """Split a single long segment by newline, then by sentence."""
        lines = text.splitlines()
        chunks: List[str] = []
        current = ""
        for line in lines:
            if not current:
                current = line
            elif len(current) + len(line) < max_sz:
                current += "\n" + line
            else:
                chunks.append(current)
                current = line
        if current:
            chunks.append(current)
        return chunks
