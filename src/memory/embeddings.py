"""Embedding provider for memory search.

Primary: sentence-transformers (all-MiniLM-L6-v2) -- good Chinese support.
Fallback: TF-IDF vectorizer via sklearn when sentence-transformers is unavailable.
"""

from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)

# We keep the np import lazy so the module can load without numpy installed.
NUMPY_AVAILABLE = True
try:
    import numpy as np
except ImportError:
    NUMPY_AVAILABLE = False
    np = None  # type: ignore[assignment]


class EmbeddingProvider:
    """Provides text embeddings via sentence-transformers or TF-IDF fallback."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model = None
        self._tfidf = None
        self._loaded = False

    # ------------------------------------------------------------------
    # lazy loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        # Try sentence-transformers first
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            logger.info(
                "Loaded sentence-transformers model: %s", self.model_name
            )
            return
        except ImportError:
            logger.info(
                "sentence-transformers not installed; falling back to TF-IDF"
            )
        except Exception as exc:
            logger.warning(
                "Failed to load sentence-transformers (%s); falling back to TF-IDF",
                exc,
            )

        # Fallback: TF-IDF
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer

            self._tfidf = TfidfVectorizer(
                max_features=5000,
                stop_words="english",
                token_pattern=r"(?u)\b\w+\b",
                sublinear_tf=True,
            )
            self._fit_tfidf()
            logger.info("Loaded TF-IDF fallback vectorizer")
        except ImportError:
            logger.error(
                "Neither sentence-transformers nor sklearn is installed. "
                "Embeddings will not work."
            )

    def _fit_tfidf(self) -> None:
        """Fit TF-IDF on a small Chinese+English corpus so transform works."""
        _corpus = [
            "股票 市场 A股 投资 交易 基金 指数 行情",
            "金融 经济 宏观 政策 利率 信贷 货币 社融",
            "技术 分析 趋势 动量 均线 K线 成交量 MACD RSI",
            "价值 投资 估值 PE PB ROE 股息 现金流 财报",
            "风险 管理 仓位 止损 对冲 波动率 回撤 夏普",
        ]
        self._tfidf.fit(_corpus)  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def embed(self, texts: List[str]) -> np.ndarray:  # type: ignore[name-defined]
        """Return embedding matrix of shape (len(texts), dim)."""
        self._load()
        if not NUMPY_AVAILABLE:
            raise RuntimeError("numpy is required for embeddings")

        if self._model is not None:
            return self._model.encode(texts, show_progress_bar=False)  # type: ignore[return-value]

        if self._tfidf is not None:
            return self._tfidf.transform(texts).toarray()  # type: ignore[return-value]

        raise RuntimeError(
            "No embedding backend available. Install sentence-transformers or sklearn."
        )

    def cosine_similarity(
        self, a: np.ndarray, b: np.ndarray  # type: ignore[name-defined]
    ) -> float:
        """Cosine similarity between two 1-D vectors."""
        if not NUMPY_AVAILABLE:
            raise RuntimeError("numpy is required for cosine similarity")
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    @property
    def dimension(self) -> int:
        """Return embedding dimension."""
        dummy = self.embed(["test"])
        return dummy.shape[1]
