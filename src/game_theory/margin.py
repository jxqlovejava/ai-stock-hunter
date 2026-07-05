"""Margin trading cycle analysis — 融资融券 balance trends and sentiment signals.

Tracks: 融资余额变化趋势, 融资买入占比, 融券余额变化
AKShare primary (SSE margin data), SZSE fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class MarginProfile:
    """Margin trading composite snapshot."""

    # Core indicators
    margin_balance: Optional[float] = None  # 融资余额 (亿元)
    margin_balance_trend: str = "stable"  # "rising" / "falling" / "stable"
    margin_buy_amount: Optional[float] = None  # 当日融资买入额 (亿元)
    margin_buy_ratio: Optional[float] = None  # 融资买入额 / 总成交额
    margin_buy_ratio_trend: str = "stable"
    short_balance: Optional[float] = None  # 融券余额 (亿元)
    short_balance_change_pct: Optional[float] = None  # 融券余额变化率 (%)

    # Derived signals
    margin_signal: str = "neutral"  # "bullish" / "bearish" / "neutral"
    leverage_sentiment: str = "neutral"  # "greedy" / "fearful" / "neutral"
    short_pressure: str = "low"  # "high" / "moderate" / "low"

    # Composite
    score: int = 50  # 0-100, higher = bullish margin sentiment
    updated_at: datetime = field(default_factory=datetime.now)


class MarginAnalyzer:
    """Analyze margin trading data for market sentiment signals.

    Primary: AKShare SSE margin data (stock_margin_sse / stock_margin_detail_sse).
    Fallback: AKShare SZSE margin data (stock_margin_szse).
    """

    # Thresholds
    MARGIN_BUY_RATIO_HIGH = 10.0  # 融资买入占比 > 10% → hot money active
    MARGIN_BUY_RATIO_LOW = 6.0  # 融资买入占比 < 6% → risk-off
    MARGIN_BALANCE_MA_DAYS = 5  # 5-day moving window for trend detection
    SHORT_BALANCE_SPIKE = 15.0  # 融券余额日增 > 15% → short pressure alert

    def __init__(self):
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(minutes=15)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self) -> MarginProfile:
        """Fetch margin data and compute composite sentiment signals."""
        signals_missing = 0

        # Fetch SSE margin data
        margin_balance = self._get_margin_balance()
        if margin_balance is None:
            signals_missing += 1

        margin_buy_ratio = self._get_margin_buy_ratio()

        short_balance = self._get_short_balance()
        short_change = self._get_short_balance_change_pct()

        # Compute trends
        balance_trend = self._compute_balance_trend()

        # Compute buy ratio trend
        buy_ratio_trend = self._compute_buy_ratio_trend()

        # Signal classification
        margin_signal = self._classify_margin_signal(
            balance_trend, margin_buy_ratio, short_change
        )

        # Leverage sentiment
        leverage_sentiment = self._classify_leverage_sentiment(
            margin_buy_ratio, balance_trend
        )

        # Short pressure
        short_pressure = self._classify_short_pressure(short_change)

        # Composite score
        score = self._compute_score(
            balance_trend, margin_buy_ratio, short_change
        )

        # Confidence
        confidence = max(0.3, 1.0 - signals_missing * 0.15)

        return MarginProfile(
            margin_balance=margin_balance,
            margin_balance_trend=balance_trend,
            margin_buy_ratio=margin_buy_ratio,
            margin_buy_ratio_trend=buy_ratio_trend,
            short_balance=short_balance,
            short_balance_change_pct=short_change,
            margin_signal=margin_signal,
            leverage_sentiment=leverage_sentiment,
            short_pressure=short_pressure,
            score=score,
        )

    # ------------------------------------------------------------------
    # Classification logic
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_margin_signal(
        balance_trend: str,
        buy_ratio: Optional[float],
        short_change: Optional[float],
    ) -> str:
        """Classify overall margin signal: bullish / bearish / neutral."""
        bullish = 0
        bearish = 0

        if balance_trend == "rising":
            bullish += 1
        elif balance_trend == "falling":
            bearish += 1

        if buy_ratio is not None:
            if buy_ratio > MarginAnalyzer.MARGIN_BUY_RATIO_HIGH:
                bullish += 1
            elif buy_ratio < MarginAnalyzer.MARGIN_BUY_RATIO_LOW:
                bearish += 1

        if short_change is not None:
            if short_change > MarginAnalyzer.SHORT_BALANCE_SPIKE:
                bearish += 1
            elif short_change < -5:
                bullish += 1  # short covering

        if bullish > bearish:
            return "bullish"
        elif bearish > bullish:
            return "bearish"
        return "neutral"

    @staticmethod
    def _classify_leverage_sentiment(
        buy_ratio: Optional[float], balance_trend: str
    ) -> str:
        """Classify leverage sentiment: greedy / fearful / neutral."""
        if buy_ratio is not None and buy_ratio > 11 and balance_trend == "rising":
            return "greedy"
        if buy_ratio is not None and buy_ratio < 5 and balance_trend == "falling":
            return "fearful"
        return "neutral"

    @staticmethod
    def _classify_short_pressure(short_change: Optional[float]) -> str:
        """Classify short-selling pressure level."""
        if short_change is None:
            return "low"
        if short_change > MarginAnalyzer.SHORT_BALANCE_SPIKE:
            return "high"
        if short_change > 5:
            return "moderate"
        return "low"

    @staticmethod
    def _compute_score(
        balance_trend: str,
        buy_ratio: Optional[float],
        short_change: Optional[float],
    ) -> int:
        """Compute 0-100 composite margin sentiment score."""
        score = 50

        # Balance trend contribution (±15)
        if balance_trend == "rising":
            score += 15
        elif balance_trend == "falling":
            score -= 15

        # Buy ratio contribution (±20)
        if buy_ratio is not None:
            if buy_ratio > 12:
                score += 20
            elif buy_ratio > 10:
                score += 10
            elif buy_ratio > 8:
                score += 5
            elif buy_ratio < 5:
                score -= 20
            elif buy_ratio < 6:
                score -= 10
            elif buy_ratio < 7:
                score -= 5

        # Short balance contribution (±15)
        if short_change is not None:
            if short_change > 20:
                score -= 15
            elif short_change > 10:
                score -= 10
            elif short_change > 5:
                score -= 5
            elif short_change < -10:
                score += 10
            elif short_change < -5:
                score += 5

        return max(0, min(100, score))

    def _compute_balance_trend(self) -> str:
        """Compute margin balance trend over 5-day window."""
        try:
            import akshare as ak

            df = ak.stock_margin_sse(start_date="")
            if df is not None and len(df) >= self.MARGIN_BALANCE_MA_DAYS:
                recent = df.tail(self.MARGIN_BALANCE_MA_DAYS)
                # Look for 融资余额 column
                bal_col = None
                for col in df.columns:
                    if "融资余额" in str(col) or "margin_balance" in str(col).lower():
                        bal_col = col
                        break
                if bal_col is None and len(df.columns) > 0:
                    # Try numeric columns
                    for col in df.columns:
                        if df[col].dtype in ("float64", "int64"):
                            bal_col = col
                            break

                if bal_col is not None:
                    first = float(recent[bal_col].iloc[0])
                    last = float(recent[bal_col].iloc[-1])
                    if last > first * 1.02:  # 2%+ increase
                        return "rising"
                    elif last < first * 0.98:  # 2%+ decrease
                        return "falling"
        except Exception as e:
            logger.warning("Margin balance trend computation failed: %s", e)

        return "stable"

    def _compute_buy_ratio_trend(self) -> str:
        """Compute margin buy ratio trend."""
        try:
            import akshare as ak

            df = ak.stock_margin_detail_sse(date="")
            if df is not None and len(df) >= self.MARGIN_BALANCE_MA_DAYS:
                recent = df.tail(self.MARGIN_BALANCE_MA_DAYS)
                # Try to find ratio or compute from buy amount
                buy_col = None
                for col in df.columns:
                    col_str = str(col)
                    if "融资买入" in col_str or "margin_buy" in col_str.lower():
                        buy_col = col
                        break
                if buy_col is not None:
                    first = float(recent[buy_col].iloc[0])
                    last = float(recent[buy_col].iloc[-1])
                    if last > first * 1.05:
                        return "rising"
                    elif last < first * 0.95:
                        return "falling"
        except Exception as e:
            logger.warning("Margin buy ratio trend computation failed: %s", e)

        return "stable"

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _get_margin_balance(self) -> Optional[float]:
        """Fetch current 融资余额 (亿元) from AKShare SSE."""
        cache_key = "margin_balance"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak

            df = ak.stock_margin_sse(start_date="")
            if df is not None and len(df) > 0:
                for col in df.columns:
                    col_str = str(col)
                    if "融资余额" in col_str:
                        val = float(df[col_str].iloc[-1])
                        # AKShare may return in 万元, convert to 亿元
                        if val > 100000:
                            val = val / 10000
                        self._cache_set(cache_key, val)
                        return val
                # Fallback: use last numeric column
                for col in df.columns:
                    if df[col].dtype in ("float64", "int64"):
                        val = float(df[col].iloc[-1])
                        if val > 100000:
                            val = val / 10000
                        self._cache_set(cache_key, val)
                        return val
        except Exception as e:
            logger.warning("AKShare SSE margin balance fetch failed: %s", e)

        # Fallback: try SZSE
        try:
            import akshare as ak

            df = ak.stock_margin_szse(date="")
            if df is not None and len(df) > 0:
                for col in df.columns:
                    if df[col].dtype in ("float64", "int64"):
                        val = float(df[col].iloc[-1])
                        if val > 100000:
                            val = val / 10000
                        self._cache_set(cache_key, val)
                        return val
        except Exception as e:
            logger.warning("AKShare SZSE margin balance fetch failed: %s", e)

        return None

    def _get_margin_buy_ratio(self) -> Optional[float]:
        """Fetch margin buy / total turnover ratio."""
        cache_key = "margin_buy_ratio"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak

            # Try margin detail data
            df = ak.stock_margin_detail_sse(date="")
            if df is not None and len(df) > 0:
                buy_amount = None
                total_turnover = None
                for col in df.columns:
                    col_str = str(col)
                    if "融资买入额" in col_str or "融资买入" in col_str:
                        buy_amount = float(df[col_str].iloc[-1])
                    if "成交额" in col_str or "融资融券余额" in col_str:
                        total_turnover = float(df[col_str].iloc[-1])
                if buy_amount and total_turnover and total_turnover > 0:
                    ratio = round((buy_amount / total_turnover) * 100, 2)
                    self._cache_set(cache_key, ratio)
                    return ratio
        except Exception as e:
            logger.warning("AKShare margin detail fetch failed: %s", e)

        # Fallback: estimate from market data
        val = self._query_guosen("融资买入占比")
        if val is not None:
            self._cache_set(cache_key, val)
        return val

    def _get_short_balance(self) -> Optional[float]:
        """Fetch current 融券余额 (亿元)."""
        cache_key = "short_balance"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak

            df = ak.stock_margin_sse(start_date="")
            if df is not None and len(df) > 0:
                for col in df.columns:
                    col_str = str(col)
                    if "融券余额" in col_str:
                        val = float(df[col_str].iloc[-1])
                        if val > 100000:
                            val = val / 10000
                        self._cache_set(cache_key, val)
                        return val
        except Exception as e:
            logger.warning("AKShare SSE short balance fetch failed: %s", e)

        return None

    def _get_short_balance_change_pct(self) -> Optional[float]:
        """Compute short balance daily change percentage."""
        cache_key = "short_change_pct"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak

            df = ak.stock_margin_sse(start_date="")
            if df is not None and len(df) >= 2:
                for col in df.columns:
                    col_str = str(col)
                    if "融券余额" in col_str:
                        current = float(df[col_str].iloc[-1])
                        previous = float(df[col_str].iloc[-2])
                        if previous > 0:
                            change = round(
                                ((current - previous) / previous) * 100, 2
                            )
                            self._cache_set(cache_key, change)
                            return change
        except Exception as e:
            logger.warning("AKShare short balance change computation failed: %s", e)

        return None

    def _query_guosen(self, query: str) -> Optional[float]:
        """Fallback: query Guosen provider."""
        try:
            from src.data.guosen import GuosenProvider

            gs = GuosenProvider()
            text = gs.get_macro(query)
            if text:
                return self._extract_first_number(text)
        except Exception:
            pass
        return None

    @staticmethod
    def _extract_first_number(text: str) -> Optional[float]:
        """Extract the first percentage or decimal number from text."""
        import re

        patterns = [
            r"([\d.]+)\s*%",
            r"同比[增长]*\s*([\d.]+)",
            r"为\s*([\d.]+)",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    continue
        return None

    # ------------------------------------------------------------------
    # Simple cache
    # ------------------------------------------------------------------

    def _cache_get(self, key: str) -> Optional[object]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, val = entry
        if datetime.now() - ts < self._cache_ttl:
            return val
        del self._cache[key]
        return None

    def _cache_set(self, key: str, val: object) -> None:
        self._cache[key] = (datetime.now(), val)

    def cache_clear(self) -> None:
        self._cache.clear()
