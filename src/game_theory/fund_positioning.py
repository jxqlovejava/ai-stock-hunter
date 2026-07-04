"""Public fund (公募) positioning and crowding analysis.

Tracks: fund heavy-holding overlap, sector crowding, new fund issuance,
estimated positioning from NAV deviation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FundCrowdingSignal:
    crowding_score: int = 50  # 0-100, >70 = crowded
    top_holdings_overlap_ratio: float = 0.0  # 公募前50重仓股重叠度
    sector_crowding: dict[str, float] = field(default_factory=dict)
    new_fund_issuance_trend: str = "stable"  # "rising" / "stable" / "falling"
    estimated_positioning_pct: Optional[float] = None  # 估算公募仓位%
    risk_level: str = "low"  # "low" / "medium" / "high"
    crowded_sectors: list[str] = field(default_factory=list)
    recommended_action: str = "neutral"  # "avoid_overcrowded" / "follow_institutions" / "neutral"
    updated_at: datetime = field(default_factory=datetime.now)


class FundPositioningAnalyzer:
    """Analyze public fund positioning and detect crowding risks."""

    def __init__(self):
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(hours=24)  # Fund data updates slowly

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self) -> FundCrowdingSignal:
        """Compute fund crowding signal from available data sources."""
        signal = FundCrowdingSignal()

        # Top holdings overlap
        overlap = self._compute_holdings_overlap()
        if overlap is not None:
            signal.top_holdings_overlap_ratio = overlap

        # Sector crowding
        sector_crowding = self._compute_sector_crowding()
        if sector_crowding:
            signal.sector_crowding = sector_crowding

        # New fund issuance trend
        signal.new_fund_issuance_trend = self._detect_new_fund_trend()

        # Estimated positioning
        signal.estimated_positioning_pct = self._estimate_positioning()

        # Crowding scoring
        signal.crowding_score = self._compute_crowding_score(signal)

        # Risk level
        if signal.crowding_score >= 70:
            signal.risk_level = "high"
            signal.recommended_action = "avoid_overcrowded"
        elif signal.crowding_score >= 50:
            signal.risk_level = "medium"
            signal.recommended_action = "neutral"
        else:
            signal.risk_level = "low"
            signal.recommended_action = "follow_institutions"

        # Crowded sectors
        signal.crowded_sectors = [
            s for s, ratio in signal.sector_crowding.items() if ratio > 0.15
        ]

        return signal

    # ------------------------------------------------------------------
    # Crowding scoring
    # ------------------------------------------------------------------

    def _compute_crowding_score(self, s: FundCrowdingSignal) -> int:
        """Compute 0-100 crowding score (higher = more crowded)."""
        score = 30.0  # Base

        # Overlap ratio signal
        if s.top_holdings_overlap_ratio > 0.7:
            score += 30
        elif s.top_holdings_overlap_ratio > 0.5:
            score += 15

        # Sector crowding
        if s.sector_crowding:
            max_crowd = max(s.sector_crowding.values()) if s.sector_crowding else 0
            score += min(max_crowd * 200, 30)

        # New fund issuance
        if s.new_fund_issuance_trend == "rising":
            score += 10  # New money coming in → less crowding
        elif s.new_fund_issuance_trend == "falling":
            score += 15  # No new money → existing positions more crowded

        # Estimated positioning
        if s.estimated_positioning_pct is not None:
            if s.estimated_positioning_pct > 88:
                score += 15  # Near fully invested → limited buying power
            elif s.estimated_positioning_pct < 80:
                score -= 10  # Has dry powder

        return max(0, min(100, int(score)))

    # ------------------------------------------------------------------
    # Sub-computations
    # ------------------------------------------------------------------

    def _compute_holdings_overlap(self) -> Optional[float]:
        """Estimate overlap ratio of top fund holdings.

        Higher overlap = more concentrated = higher crowding risk.
        """
        try:
            import akshare as ak
            # Try to fetch fund industry holding data
            df = ak.fund_portfolio_hold_detail_em(date=datetime.now().strftime("%Y"))
            if df is not None and len(df) > 0:
                # Count how many top stocks appear across multiple funds
                stock_counts = df.groupby("股票代码").size() if "股票代码" in df.columns else None
                if stock_counts is not None and len(stock_counts) > 0:
                    # Overlap ratio = stocks held by >3 funds / total unique stocks
                    multi_held = (stock_counts > 3).sum()
                    total = len(stock_counts)
                    return float(multi_held / total) if total > 0 else 0.0
        except Exception as e:
            logger.debug("Holdings overlap computation failed: %s", e)

        # Fallback: query Guosen macro
        return self._query_guosen_numeric("公募基金重仓股持仓重叠度")

    def _compute_sector_crowding(self) -> dict[str, float]:
        """Compute sector crowding = fund holdings / free-float market cap by sector."""
        crowding: dict[str, float] = {}
        try:
            import akshare as ak
            df = ak.fund_portfolio_industry_hold_em(date=datetime.now().strftime("%Y"))
            if df is not None and len(df) > 0:
                for _, row in df.iterrows():
                    sector = str(row.iloc[0]) if len(row) > 0 else ""
                    try:
                        ratio = float(row.iloc[-1]) / 100.0 if len(row) > 1 else 0.0
                        crowding[sector] = ratio
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            logger.debug("Sector crowding computation failed: %s", e)
        return crowding

    def _detect_new_fund_trend(self, months: int = 3) -> str:
        """Detect trend in new fund issuance."""
        try:
            import akshare as ak
            df = ak.fund_scale_change_sina()
            if df is not None and len(df) >= months:
                recent = df.iloc[-months:]
                # Look for issuance or scale change
                for col in df.columns:
                    if "新发" in str(col) or "发行" in str(col) or "规模" in str(col):
                        import pandas as pd
                        vals = pd.to_numeric(df[col], errors="coerce").dropna()
                        if len(vals) >= months:
                            recent_avg = vals.iloc[-months:].mean()
                            prev_avg = vals.iloc[-2 * months : -months].mean()
                            if prev_avg > 0:
                                change = (recent_avg - prev_avg) / prev_avg
                                if change > 0.1:
                                    return "rising"
                                elif change < -0.1:
                                    return "falling"
                            return "stable"
        except Exception as e:
            logger.debug("New fund trend detection failed: %s", e)
        return "stable"

    def _estimate_positioning(self) -> Optional[float]:
        """Estimate current fund positioning percentage via Guosen macro."""
        val = self._query_guosen_numeric("公募基金仓位估算 股票仓位")
        if val is not None:
            # Guosen returns percentage (e.g., 85.5 for 85.5%)
            if val > 1:
                return val  # Already in percentage
            return val * 100
        return None

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def _query_guosen_numeric(self, query: str) -> Optional[float]:
        """Query Guosen macro and extract a numeric value."""
        try:
            from src.data.guosen import GuosenProvider
            gs = GuosenProvider()
            text = gs.get_macro(query)
            if text:
                import re
                # Try to find percentage or decimal
                m = re.search(r"([\d.]+)\s*%", text)
                if m:
                    return float(m.group(1))
                m = re.search(r"([\d.]+)", text)
                if m:
                    val = float(m.group(1))
                    if 0 < val <= 100:
                        return val
        except Exception:
            pass
        return None

    def cache_clear(self) -> None:
        self._cache.clear()
