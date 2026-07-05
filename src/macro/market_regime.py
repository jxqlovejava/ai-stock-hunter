"""Market regime classifier — volatility, trend, and risk-on/off detection.

Detects 6 market states without full HMM/GARCH:
  - BULL_TRENDING / BEAR_TRENDING / HIGH_VOL_CRISIS
  - LOW_VOL_DRIFT / RISK_ON / RISK_OFF

Uses rolling volatility, moving average cross, and breadth indicators.
ponytail: simple statistical thresholds instead of full HMM, add HMM when regime persistence matters.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class MarketRegime(str, Enum):
    BULL_TRENDING = "bull_trending"  # 上涨趋势
    BEAR_TRENDING = "bear_trending"  # 下跌趋势
    HIGH_VOL_CRISIS = "high_vol_crisis"  # 高波动危机
    LOW_VOL_DRIFT = "low_vol_drift"  # 低波动横盘
    RISK_ON = "risk_on"  # 风险偏好
    RISK_OFF = "risk_off"  # 风险规避


@dataclass
class RegimeProfile:
    """Market regime snapshot."""

    regime: MarketRegime = MarketRegime.LOW_VOL_DRIFT
    confidence: float = 0.5
    volatility: Optional[float] = None  # 20-day annualized vol (%)
    volatility_percentile: Optional[float] = None  # 1-year vol percentile
    ma_signal: str = "neutral"  # "bullish" / "bearish" / "neutral"
    breadth: Optional[float] = None  # % stocks above 20-day MA
    trend_strength: Optional[float] = None  # ADX-like
    risk_appetite: str = "neutral"  # "risk_on" / "risk_off" / "neutral"

    # Trading implications
    recommended_exposure: float = 0.6  # 0.0-1.0 suggested portfolio exposure
    use_trend_following: bool = True
    use_mean_reversion: bool = False
    tighten_stops: bool = False
    updated_at: datetime = field(default_factory=datetime.now)


class RegimeClassifier:
    """Detect market regime from price and breadth data."""

    # Thresholds
    VOL_HIGH_PCT = 80  # > 80th percentile vol = high vol
    VOL_LOW_PCT = 30  # < 30th percentile = low vol
    BREADTH_BULLISH = 60  # > 60% stocks above MA = bullish
    BREADTH_BEARISH = 40  # < 40% = bearish

    def __init__(self):
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(minutes=30)

    def classify(
        self,
        prices: list[float],
        highs: Optional[list[float]] = None,
        lows: Optional[list[float]] = None,
        breadth: Optional[float] = None,
        advance_decline_ratio: Optional[float] = None,
    ) -> RegimeProfile:
        """Classify current market regime from price data.

        Args:
            prices: Recent closing prices (at least 60 data points recommended).
            highs: High prices for ATR calculation.
            lows: Low prices for ATR calculation.
            breadth: % of stocks above 20-day MA (market breadth).
            advance_decline_ratio: Advance/decline ratio.
        """
        if len(prices) < 20:
            return RegimeProfile()

        profile = RegimeProfile()

        # 1. Volatility regime
        vol, vol_pct = self._compute_volatility(prices, highs, lows)
        profile.volatility = vol
        profile.volatility_percentile = vol_pct

        # 2. Trend signal (MA cross)
        ma_signal, trend_strength = self._compute_trend(prices)
        profile.ma_signal = ma_signal
        profile.trend_strength = trend_strength

        # 3. Breadth
        profile.breadth = breadth

        # 4. Risk appetite
        profile.risk_appetite = self._classify_risk_appetite(
            ma_signal, breadth, advance_decline_ratio
        )

        # 5. Classify regime
        profile.regime = self._classify_regime(
            vol, vol_pct, ma_signal, trend_strength, breadth, profile.risk_appetite
        )

        # 6. Trading implications
        profile.recommended_exposure = self._recommend_exposure(profile.regime, vol)
        profile.use_trend_following = profile.regime in (
            MarketRegime.BULL_TRENDING, MarketRegime.BEAR_TRENDING
        )
        profile.use_mean_reversion = profile.regime == MarketRegime.LOW_VOL_DRIFT
        profile.tighten_stops = profile.regime in (
            MarketRegime.HIGH_VOL_CRISIS, MarketRegime.BEAR_TRENDING
        )

        profile.confidence = self._compute_confidence(vol_pct, trend_strength, breadth)

        return profile

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_regime(
        vol: float,
        vol_pct: float,
        ma_signal: str,
        trend_strength: float,
        breadth: Optional[float],
        risk_appetite: str,
    ) -> MarketRegime:
        """Determine market regime from indicators."""
        high_vol = vol_pct > RegimeClassifier.VOL_HIGH_PCT if vol_pct else False
        low_vol = vol_pct < RegimeClassifier.VOL_LOW_PCT if vol_pct else False
        bullish = ma_signal == "bullish"
        bearish = ma_signal == "bearish"

        # Crisis: high vol + bearish
        if high_vol and bearish:
            return MarketRegime.HIGH_VOL_CRISIS

        # Bull trending
        if bullish and trend_strength > 25:
            return MarketRegime.BULL_TRENDING

        # Bear trending
        if bearish and trend_strength > 25:
            return MarketRegime.BEAR_TRENDING

        # Risk on/off from breadth
        if risk_appetite == "risk_on" and not bearish:
            return MarketRegime.RISK_ON
        if risk_appetite == "risk_off" and not bullish:
            return MarketRegime.RISK_OFF

        # Default: low vol drift
        if low_vol:
            return MarketRegime.LOW_VOL_DRIFT

        # Fallback
        if bullish:
            return MarketRegime.BULL_TRENDING
        if bearish:
            return MarketRegime.BEAR_TRENDING
        return MarketRegime.LOW_VOL_DRIFT

    @staticmethod
    def _classify_risk_appetite(
        ma_signal: str,
        breadth: Optional[float],
        ad_ratio: Optional[float],
    ) -> str:
        """Classify risk appetite."""
        risk_on = 0
        risk_off = 0

        if ma_signal == "bullish":
            risk_on += 1
        elif ma_signal == "bearish":
            risk_off += 1

        if breadth is not None:
            if breadth > RegimeClassifier.BREADTH_BULLISH:
                risk_on += 1
            elif breadth < RegimeClassifier.BREADTH_BEARISH:
                risk_off += 1

        if ad_ratio is not None:
            if ad_ratio > 1.5:
                risk_on += 1
            elif ad_ratio < 0.5:
                risk_off += 1

        if risk_on > risk_off:
            return "risk_on"
        elif risk_off > risk_on:
            return "risk_off"
        return "neutral"

    # ------------------------------------------------------------------
    # Computation
    # ------------------------------------------------------------------

    def _compute_volatility(
        self, prices: list[float], highs=None, lows=None
    ) -> tuple[float, float]:
        """20-day annualized volatility and 1-year percentile."""
        arr = np.array(prices[-60:])  # up to 60 days
        returns = np.diff(arr) / arr[:-1]
        vol = float(np.std(returns[-20:]) * np.sqrt(252) * 100) if len(returns) >= 20 else 30.0

        # 1-year percentile (if enough data)
        if len(returns) >= 60:
            rolling_vols = [
                np.std(returns[i:i+20]) * np.sqrt(252) * 100
                for i in range(len(returns) - 20)
            ]
            pct = (sum(1 for v in rolling_vols if v <= vol) / len(rolling_vols)) * 100
        else:
            pct = 50.0

        return vol, pct

    def _compute_trend(self, prices: list[float]) -> tuple[str, float]:
        """MA crossover signal and ADX-like trend strength."""
        arr = np.array(prices)
        if len(arr) < 20:
            return "neutral", 0.0

        ma_short = np.mean(arr[-5:])
        ma_mid = np.mean(arr[-10:])
        ma_long = np.mean(arr[-20:])

        if ma_short > ma_mid > ma_long:
            signal = "bullish"
        elif ma_short < ma_mid < ma_long:
            signal = "bearish"
        else:
            signal = "neutral"

        # ADX-like: directional movement / total range
        if len(arr) >= 20:
            up_moves = np.diff(arr[-20:])
            plus_dm = np.sum(np.maximum(up_moves, 0))
            minus_dm = np.sum(np.maximum(-up_moves, 0))
            tr = np.sum(np.abs(up_moves))
            if tr > 0:
                dx = abs(plus_dm - minus_dm) / tr * 100
                trend = float(dx)
            else:
                trend = 0.0
        else:
            trend = 0.0

        return signal, trend

    @staticmethod
    def _recommend_exposure(regime: MarketRegime, vol: float) -> float:
        """Recommend portfolio exposure based on regime."""
        exposure = {
            MarketRegime.BULL_TRENDING: 0.9,
            MarketRegime.RISK_ON: 0.8,
            MarketRegime.LOW_VOL_DRIFT: 0.6,
            MarketRegime.RISK_OFF: 0.3,
            MarketRegime.BEAR_TRENDING: 0.2,
            MarketRegime.HIGH_VOL_CRISIS: 0.1,
        }
        base = exposure.get(regime, 0.5)
        # Reduce further if vol is extreme
        if vol > 40:
            base *= 0.5
        return base

    @staticmethod
    def _compute_confidence(
        vol_pct: float, trend_strength: float, breadth: Optional[float]
    ) -> float:
        signals = 0
        available = 0
        if vol_pct:
            available += 1
            if vol_pct > 70 or vol_pct < 30:
                signals += 1  # clear vol signal
        if trend_strength > 20:
            signals += 1
            available += 1
        if breadth is not None:
            available += 1
            if breadth > 60 or breadth < 40:
                signals += 1
        return round(max(0.3, signals / max(available, 1)), 2)

    def cache_clear(self) -> None:
        self._cache.clear()
