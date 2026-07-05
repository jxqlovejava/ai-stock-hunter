"""Enhanced sentiment analysis — multi-source aggregation + divergence detection.

Boosts NLP sentiment_score from 68 to target 80+ via:
  1. Multi-source weighted aggregation (social media + news + research reports)
  2. Sentiment divergence scoring (bull-bear spread)
  3. Volume-weighted sentiment (高讨论量=高信号权重)
  4. Sentiment momentum (情绪变化速度)
  5. Source credibility weighting
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SentimentSource:
    """Single sentiment data source."""

    source_name: str  # "雪球" / "微博" / "东方财富股吧" / "财联社" / "研报"
    source_type: str  # "social" / "news" / "research"
    raw_sentiment: float  # -1.0 to 1.0
    confidence: float  # 0.0-1.0 (source credibility)
    volume: int = 0  # number of items
    momentum: float = 0.0  # sentiment change vs previous period
    keywords_pos: list[str] = field(default_factory=list)
    keywords_neg: list[str] = field(default_factory=list)


@dataclass
class EnhancedSentiment:
    """Multi-source aggregated sentiment result."""

    symbol: str = ""
    name: str = ""

    # Aggregated scores
    composite_sentiment: float = 0.0  # -1.0 to 1.0
    composite_confidence: float = 0.5  # 0.0-1.0
    intensity: float = 0.0  # 0.0-1.0, how strong the sentiment is (abs + volume)

    # Sources
    sources: list[SentimentSource] = field(default_factory=list)

    # Divergence
    sentiment_divergence: float = 0.0  # 0.0-1.0, high = disagreement
    bull_bear_ratio: float = 1.0  # bullish / bearish item count

    # Momentum
    sentiment_momentum: float = 0.0  # -1.0 to 1.0, sentiment acceleration
    sentiment_trend: str = "stable"  # "improving" / "deteriorating" / "stable"

    # Signal
    signal: str = "NEUTRAL"  # "BULLISH" / "BEARISH" / "NEUTRAL" / "DIVERGENT"
    trading_hint: str = ""
    updated_at: datetime = field(default_factory=datetime.now)


class SentimentEnhancer:
    """Multi-source sentiment aggregation engine.

    Takes raw sentiment from NLP processors + social media sources,
    computes weighted composite with credibility and volume adjustments.
    """

    # Source credibility weights (calibrated)
    SOURCE_CREDIBILITY = {
        "研报": 0.85,
        "财联社": 0.75,
        "华尔街见闻": 0.70,
        "雪球": 0.55,
        "东方财富股吧": 0.45,
        "微博": 0.40,
        "知乎": 0.50,
        "last30days-cn": 0.60,
    }

    def __init__(self):
        self._cache: dict[str, tuple[datetime, EnhancedSentiment]] = {}
        self._cache_ttl = timedelta(minutes=15)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        symbol: str,
        name: str = "",
        raw_sources: Optional[list[dict]] = None,
    ) -> EnhancedSentiment:
        """Aggregate multiple sentiment sources into enhanced composite.

        Args:
            symbol: Stock code.
            name: Stock name.
            raw_sources: List of dicts with keys:
                source_name, raw_sentiment, volume, keywords_pos, keywords_neg, prev_sentiment
        """
        result = EnhancedSentiment(symbol=symbol, name=name)
        if not raw_sources:
            return result

        sources = []
        total_weight = 0.0
        weighted_sentiment = 0.0
        total_volume = 0
        bull_count = 0
        bear_count = 0

        for raw in raw_sources:
            source_name = raw.get("source_name", "unknown")
            source_type = self._classify_source_type(source_name)
            base_cred = self.SOURCE_CREDIBILITY.get(source_name, 0.50)

            raw_sent = float(raw.get("raw_sentiment", 0))
            volume = int(raw.get("volume", 1))
            prev_sent = float(raw.get("prev_sentiment", raw_sent))

            # Volume-adjusted credibility: more data = higher confidence
            vol_factor = min(1.0, volume / 100)  # max at 100 items
            credibility = base_cred * (0.7 + 0.3 * vol_factor)

            # Momentum
            momentum = raw_sent - prev_sent

            source = SentimentSource(
                source_name=source_name,
                source_type=source_type,
                raw_sentiment=round(raw_sent, 3),
                confidence=round(credibility, 2),
                volume=volume,
                momentum=round(momentum, 3),
                keywords_pos=raw.get("keywords_pos", []),
                keywords_neg=raw.get("keywords_neg", []),
            )
            sources.append(source)

            # Weighted aggregation
            weight = credibility * (1 + vol_factor * 0.3)
            weighted_sentiment += raw_sent * weight
            total_weight += weight
            total_volume += volume

            if raw_sent > 0.1:
                bull_count += 1
            elif raw_sent < -0.1:
                bear_count += 1

        result.sources = sources

        # Composite sentiment
        if total_weight > 0:
            result.composite_sentiment = round(weighted_sentiment / total_weight, 3)

        # Confidence: average source credibility × coverage
        avg_cred = sum(s.confidence for s in sources) / len(sources) if sources else 0
        coverage = min(1.0, len(sources) / 3)  # max at 3+ sources
        result.composite_confidence = round(avg_cred * coverage, 2)

        # Intensity: how strong + how much volume
        result.intensity = round(abs(result.composite_sentiment) * min(1.0, total_volume / 200), 3)

        # Bull/bear ratio
        total_sided = bull_count + bear_count
        result.bull_bear_ratio = round(bull_count / max(bear_count, 1), 2) if total_sided > 0 else 1.0

        # Divergence: high when sources disagree
        if len(sources) >= 2:
            sentiments = [s.raw_sentiment for s in sources]
            result.sentiment_divergence = round(np_std(sentiments), 3) if sentiments else 0.0

        # Momentum
        if sources:
            result.sentiment_momentum = round(
                sum(s.momentum * s.confidence for s in sources) / max(sum(s.confidence for s in sources), 0.01), 3
            )

        # Trend
        if result.sentiment_momentum > 0.1:
            result.sentiment_trend = "improving"
        elif result.sentiment_momentum < -0.1:
            result.sentiment_trend = "deteriorating"

        # Signal
        result.signal = self._classify_signal(result)

        # Trading hint
        result.trading_hint = self._generate_hint(result)

        return result

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_signal(e: EnhancedSentiment) -> str:
        """Classify sentiment signal."""
        if e.sentiment_divergence > 0.4:
            return "DIVERGENT"  # 分歧大，无一致方向

        if e.composite_sentiment > 0.2:
            if e.sentiment_momentum > 0.1:
                return "BULLISH"  # 看多+加速
            return "BULLISH"
        elif e.composite_sentiment < -0.2:
            if e.sentiment_momentum < -0.1:
                return "BEARISH"
            return "BEARISH"

        return "NEUTRAL"

    @staticmethod
    def _generate_hint(e: EnhancedSentiment) -> str:
        """Generate trading hint from sentiment profile."""
        if e.signal == "DIVERGENT":
            return "情绪分歧大，方向不明朗，建议观望或降低仓位"
        if e.signal == "BULLISH" and e.sentiment_trend == "improving":
            return f"情绪看多且加速 (强度{e.intensity:.2f})，可考虑顺势加仓"
        if e.signal == "BEARISH" and e.sentiment_trend == "deteriorating":
            return f"情绪看空且恶化 (强度{e.intensity:.2f})，建议减仓或回避"
        if e.signal == "BULLISH" and e.intensity > 0.6:
            return "情绪高度一致看多，注意拥挤反转风险"
        if e.signal == "BEARISH" and e.intensity > 0.6:
            return "情绪极度悲观，关注恐慌超卖反弹机会"
        return "情绪中性，方向不明"

    @staticmethod
    def _classify_source_type(source_name: str) -> str:
        if source_name in ("研报", "券商"):
            return "research"
        if source_name in ("财联社", "华尔街见闻"):
            return "news"
        return "social"

    def cache_clear(self) -> None:
        self._cache.clear()


def np_std(values: list[float]) -> float:
    """Standard deviation without numpy dependency."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return variance ** 0.5
