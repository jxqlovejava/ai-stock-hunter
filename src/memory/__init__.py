"""Baize memory system — Dexter's design.

Components:
  types.py        — MemoryEntry, SearchResult dataclasses
  store.py        — file-based markdown MemoryStore
  database.py     — SQLite + FTS5 MemoryDatabase
  chunker.py      — MarkdownChunker (headings → code-block-aware segments)
  embeddings.py   — EmbeddingProvider (sentence-transformers / TF-IDF fallback)
  search.py       — MemorySearch (hybrid vector + FTS5, MMR, time decay)
"""

from .chunker import MarkdownChunker
from .database import MemoryDatabase
from .embeddings import EmbeddingProvider
from .search import MemorySearch
from .store import MemoryStore
from .types import MemoryEntry, SearchResult

__all__ = [
    "MarkdownChunker",
    "MemoryDatabase",
    "MemoryEntry",
    "MemorySearch",
    "MemoryStore",
    "SearchResult",
]
