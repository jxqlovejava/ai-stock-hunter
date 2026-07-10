"""投研笔记 (Research Notes) — 双向触发的长期讨论记录系统。

Components:
  types.py   — ResearchNote, NoteStatus, NoteTopic dataclasses
  store.py   — NoteStore: file-based Markdown CRUD
  search.py  — NoteSearch: SQLite FTS5 full-text search
"""

from .search import NoteSearch
from .store import NoteStore
from .types import NoteStatus, NoteTopic, ResearchNote

__all__ = [
    "NoteSearch",
    "NoteStatus",
    "NoteStore",
    "NoteTopic",
    "ResearchNote",
]
