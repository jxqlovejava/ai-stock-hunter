"""Memory system dataclasses - Dexter's design.

MemoryEntry: single memory unit with full provenance.
SearchResult: ranked hit combining entry + score + source tag.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class MemoryEntry:
    """A single memory unit with provenance metadata."""

    id: str
    content: str
    source: str
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """Ranked search hit wrapping a MemoryEntry."""

    entry: MemoryEntry
    score: float
    source: str
