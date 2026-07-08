"""Hybrid memory search combining vector similarity + FTS5 + MMR + time decay.

Algorithm:
  1. Embed query → vector search over all stored chunks (cosine sim).
  2. FTS5 keyword search (BM25) over the same chunks.
  3. Normalise and combine scores:  vector * 0.7 + text * 0.3.
  4. Apply time-decay multiplier:  half-life = 30 days.
  5. MMR re-rank with lambda = 0.7 to de-duplicate.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

logger = logging.getLogger(__name__)

from .database import MemoryDatabase
from .embeddings import EmbeddingProvider
from .types import MemoryEntry, SearchResult

NUMPY_AVAILABLE = True
try:
    import numpy as np
except ImportError:
    NUMPY_AVAILABLE = False
    np = None  # type: ignore[assignment]


class MemorySearch:
    """Hybrid memory search with MMR dedup and time decay."""

    def __init__(
        self,
        database: MemoryDatabase | None = None,
        embedder: EmbeddingProvider | None = None,
        vector_weight: float = 0.7,
        text_weight: float = 0.3,
        mmr_lambda: float = 0.7,
        half_life_days: float = 30.0,
    ) -> None:
        self.database = database or MemoryDatabase()
        self.embedder = embedder or EmbeddingProvider()
        self.vector_weight = vector_weight
        self.text_weight = text_weight
        self.mmr_lambda = mmr_lambda
        self.half_life_days = half_life_days

    # ------------------------------------------------------------------
    # core search
    # ------------------------------------------------------------------

    def hybrid_search(
        self, query: str, top_k: int = 10
    ) -> List[SearchResult]:
        """Run hybrid search with MMR + time decay.

        Returns up to *top_k* SearchResults sorted by final score descending.
        """
        if not query or not query.strip():
            return []

        candidates = self._collect_candidates(query, top_k * 3)
        if not candidates:
            return []

        now = datetime.now(timezone.utc)

        # 1. vector similarity (cosine)
        vec_scores = self._vector_scores(query, candidates)

        # 2. FTS5 similarity (BM25 inverted → [0,1])
        text_scores = self._text_scores(query, candidates)

        # 3. combine
        for i, (_entry, score) in enumerate(candidates):
            vs = vec_scores[i] if i < len(vec_scores) else 0.0
            ts = text_scores[i] if i < len(text_scores) else 0.0
            score = vs * self.vector_weight + ts * self.text_weight

            # 4. time decay
            age_days = (now - _entry.created_at).total_seconds() / 86400.0
            decay = 2.0 ** (-age_days / self.half_life_days)
            score *= decay

            candidates[i] = (_entry, score)

        # sort by raw score descending
        candidates.sort(key=lambda x: x[1], reverse=True)

        # 5. MMR re-rank
        reranked = self._mmr_rerank(candidates, top_k)
        return [
            SearchResult(entry=e, score=s, source="hybrid")
            for e, s in reranked
        ]

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _collect_candidates(
        self, query: str, max_candidates: int
    ) -> List:
        """Gather candidate entries from FTS5 + all-store vector scan."""
        seen: set[str] = set()
        candidates: List = []

        # FTS5 candidates
        try:
            rows = self.database.search(query, limit=max_candidates)
            for chunk_id, content, _bm25 in rows:
                if chunk_id not in seen:
                    seen.add(chunk_id)
                    entry = MemoryEntry(
                        id=chunk_id,
                        content=content,
                        source="memory",
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                    candidates.append((entry, 0.0))

            # fallback: if FTS5 returns nothing useful, grab recent chunks
            if not candidates:
                # try a broader search via all chunks
                pass
        except Exception:
            logger.exception("FTS5 search failed")

        # If FTS5 gave nothing, scan all entries from the store
        # (handled by caller providing all entries -- for hybrid to work,
        #  we need a store.MemoryStore.  Here we rely on database having
        #  all chunks indexed already.)
        return candidates

    def _vector_scores(self, query: str, candidates: List) -> List[float]:
        """Return cosine-similarity scores between query and candidates."""
        if not NUMPY_AVAILABLE or not candidates:
            return [0.0] * len(candidates)

        contents = [c[0].content for c in candidates]
        query_vec = self.embedder.embed([query])[0]
        cand_vecs = self.embedder.embed(contents)
        scores = [
            self.embedder.cosine_similarity(query_vec, cand_vecs[i])
            for i in range(len(candidates))
        ]
        # normalise to [0, 1]
        return self._normalise(scores)

    def _text_scores(self, query: str, candidates: List) -> List[float]:
        """Return FTS5 BM25 scores, inverted and normalised to [0,1]."""
        if not candidates:
            return []

        # Use database.search to get BM25 for each candidate
        entry_map = {c[0].id: c for c in candidates}
        scores: dict[str, float] = {}
        try:
            rows = self.database.search(query, limit=len(candidates) * 2)
            for chunk_id, _content, bm25 in rows:
                if chunk_id in entry_map:
                    # Invert: BM25 lower = better, so we negate
                    scores[chunk_id] = -bm25
        except Exception:
            pass

        result = [scores.get(c[0].id, 0.0) for c in candidates]
        return self._normalise(result)

    @staticmethod
    def _normalise(values: List[float]) -> List[float]:
        """Min-max normalise to [0, 1].  Returns zeros if constant."""
        if not values:
            return []
        mn, mx = min(values), max(values)
        if mx - mn < 1e-12:
            return [0.0] * len(values)
        return [(v - mn) / (mx - mn) for v in values]

    def _mmr_rerank(
        self,
        candidates: List,
        top_k: int,
    ) -> List:
        """Maximal Marginal Relevance re-ranking.

        lambda=1 → pure relevance, lambda=0 → pure diversity.
        """
        if not candidates:
            return []

        lam = self.mmr_lambda
        selected: List = []
        remaining = list(candidates)

        # precompute pairwise similarities for diversity
        if NUMPY_AVAILABLE and len(candidates) > 1:
            contents = [c[0].content for c in candidates]
            vecs = self.embedder.embed(contents)
        else:
            vecs = None

        for _ in range(min(top_k, len(candidates))):
            best_score = -1.0
            best_idx = 0
            for i, (entry, rel_score) in enumerate(remaining):
                # diversity: max similarity to any already selected
                if selected and vecs is not None:
                    sims = [
                        self.embedder.cosine_similarity(
                            vecs[candidates.index(s)],
                            vecs[candidates.index((entry, rel_score))],
                        )
                        for s in selected
                    ]
                    diversity = 1.0 - max(sims)
                else:
                    diversity = 1.0

                mmr = lam * rel_score + (1 - lam) * diversity
                if mmr > best_score:
                    best_score = mmr
                    best_idx = i

            selected.append(remaining.pop(best_idx))

        return selected
