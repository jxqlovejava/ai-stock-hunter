"""Monetary-Credit dual-quadrant framework for A-share macro regime classification.

Tracks: 社融增速, M1-M2剪刀差, LPR(1Y/5Y), DR007, 信贷脉冲
Classifies into 4 quadrants with sector recommendations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class Quadrant(str, Enum):
    EASY_MONEY_EASY_CREDIT = "宽货币+宽信用"
    EASY_MONEY_TIGHT_CREDIT = "宽货币+紧信用"
    TIGHT_MONEY_EASY_CREDIT = "紧货币+宽信用"
    TIGHT_MONEY_TIGHT_CREDIT = "紧货币+紧信用"


@dataclass
class MacroRegime:
    quadrant: Quadrant
    confidence: float  # 0.0-1.0
    social_financing_growth: Optional[float] = None
    m1_m2_gap: Optional[float] = None
    lpr_1y: Optional[float] = None
    lpr_5y: Optional[float] = None
    dr007: Optional[float] = None
    credit_pulse: Optional[float] = None
    transition_signals: list[str] = field(default_factory=list)
    recommended_sectors: list[str] = field(default_factory=list)
    avoid_sectors: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=datetime.now)


# Quadrant → sector mapping
QUADRANT_SECTOR_MAP: dict[Quadrant, tuple[list[str], list[str]]] = {
    Quadrant.EASY_MONEY_EASY_CREDIT: (
        ["券商", "银行", "地产", "基建", "建材", "有色", "消费"],
        ["债券", "现金"],
    ),
    Quadrant.EASY_MONEY_TIGHT_CREDIT: (
        ["成长股", "医药", "科技", "新能源", "军工"],
        ["银行", "地产", "周期"],
    ),
    Quadrant.TIGHT_MONEY_EASY_CREDIT: (
        ["银行", "保险", "消费", "价值股"],
        ["高估值成长", "地产"],
    ),
    Quadrant.TIGHT_MONEY_TIGHT_CREDIT: (
        ["防御性消费", "公用事业", "现金", "债券"],
        ["券商", "地产", "有色", "成长股"],
    ),
}


class MonetaryCreditAnalyzer:
    """Analyze monetary and credit conditions to classify macro regime."""

    # Approximate policy rate for DR007 comparison (7-day reverse repo rate)
    POLICY_RATE = 1.50  # Latest 7-day reverse repo rate
    # Approximate nominal GDP growth for social financing comparison
    NOMINAL_GDP_GROWTH = 5.0  # Rough estimate, updated periodically

    def __init__(self):
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(hours=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self) -> MacroRegime:
        """Fetch all indicators and classify current macro regime."""
        signals_missing = 0

        sf_growth = self._get_social_financing_growth()
        if sf_growth is None:
            signals_missing += 1

        m1_m2_gap = self._get_m1_m2_gap()
        if m1_m2_gap is None:
            signals_missing += 1

        lpr_1y = self._get_lpr_1y()
        lpr_5y = self._get_lpr_5y()

        dr007 = self._get_dr007()
        if dr007 is None:
            signals_missing += 1

        credit_pulse = self._compute_credit_pulse(sf_growth)

        # Classify
        money_direction = self._classify_money(m1_m2_gap, dr007)
        credit_direction = self._classify_credit(sf_growth, credit_pulse)
        quadrant = self._to_quadrant(money_direction, credit_direction)

        # Confidence: reduce by 0.15 per missing signal
        confidence = max(0.3, 1.0 - signals_missing * 0.15)

        recommended, avoid = QUADRANT_SECTOR_MAP.get(
            quadrant, (["防御性消费", "现金"], ["券商", "周期"])
        )

        # Transition signals
        signals: list[str] = []
        if dr007 is not None and dr007 < self.POLICY_RATE - 0.1:
            signals.append("DR007低于政策利率，货币偏宽松")
        if dr007 is not None and dr007 > self.POLICY_RATE + 0.2:
            signals.append("DR007高于政策利率，货币偏紧")
        if m1_m2_gap is not None and m1_m2_gap > 3.0:
            signals.append("M1-M2剪刀差走阔，资金活化程度高")
        if m1_m2_gap is not None and m1_m2_gap < -2.0:
            signals.append("M1-M2剪刀差倒挂，资金沉淀严重")
        if sf_growth is not None and sf_growth > self.NOMINAL_GDP_GROWTH + 2:
            signals.append("社融增速显著高于名义GDP，信用扩张")
        if sf_growth is not None and sf_growth < self.NOMINAL_GDP_GROWTH - 1:
            signals.append("社融增速低于名义GDP，信用收缩")

        return MacroRegime(
            quadrant=quadrant,
            confidence=confidence,
            social_financing_growth=sf_growth,
            m1_m2_gap=m1_m2_gap,
            lpr_1y=lpr_1y,
            lpr_5y=lpr_5y,
            dr007=dr007,
            credit_pulse=credit_pulse,
            transition_signals=signals,
            recommended_sectors=recommended,
            avoid_sectors=avoid,
        )

    def get_sector_recommendations(self) -> tuple[list[str], list[str]]:
        """Return (recommended, avoid) sector lists for current regime."""
        regime = self.analyze()
        return regime.recommended_sectors, regime.avoid_sectors

    # ------------------------------------------------------------------
    # Classification logic
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_money(
        m1_m2_gap: Optional[float], dr007: Optional[float]
    ) -> str:
        """Classify monetary policy direction: 'easy', 'tight', 'neutral'."""
        easy_signals = 0
        tight_signals = 0

        if m1_m2_gap is not None:
            if m1_m2_gap > 0:
                easy_signals += 1  # M1 faster than M2 → money circulating
            elif m1_m2_gap < -3.0:
                tight_signals += 1

        if dr007 is not None:
            policy_rate = MonetaryCreditAnalyzer.POLICY_RATE
            if dr007 < policy_rate - 0.05:
                easy_signals += 1
            elif dr007 > policy_rate + 0.15:
                tight_signals += 1

        if easy_signals > tight_signals:
            return "easy"
        elif tight_signals > easy_signals:
            return "tight"
        return "neutral"

    @staticmethod
    def _classify_credit(
        sf_growth: Optional[float], credit_pulse: Optional[float]
    ) -> str:
        """Classify credit policy direction: 'easy', 'tight', 'neutral'."""
        easy_signals = 0
        tight_signals = 0

        if sf_growth is not None:
            nominal_gdp = MonetaryCreditAnalyzer.NOMINAL_GDP_GROWTH
            if sf_growth > nominal_gdp + 1.5:
                easy_signals += 1
            elif sf_growth < nominal_gdp - 0.5:
                tight_signals += 1

        if credit_pulse is not None:
            if credit_pulse > 0.2:
                easy_signals += 1
            elif credit_pulse < -0.2:
                tight_signals += 1

        if easy_signals > tight_signals:
            return "easy"
        elif tight_signals > easy_signals:
            return "tight"
        return "neutral"

    @staticmethod
    def _to_quadrant(money: str, credit: str) -> Quadrant:
        if money == "easy" and credit == "easy":
            return Quadrant.EASY_MONEY_EASY_CREDIT
        elif money == "easy" and credit in ("tight", "neutral"):
            return Quadrant.EASY_MONEY_TIGHT_CREDIT
        elif money in ("tight", "neutral") and credit == "easy":
            return Quadrant.TIGHT_MONEY_EASY_CREDIT
        return Quadrant.TIGHT_MONEY_TIGHT_CREDIT

    @staticmethod
    def _compute_credit_pulse(sf_growth: Optional[float]) -> Optional[float]:
        """Credit pulse = (current SF growth - GDP growth) normalized."""
        if sf_growth is None:
            return None
        return sf_growth - MonetaryCreditAnalyzer.NOMINAL_GDP_GROWTH

    # ------------------------------------------------------------------
    # Data fetching (AKShare + Guosen fallback)
    # ------------------------------------------------------------------

    def _get_social_financing_growth(self) -> Optional[float]:
        """Fetch 社融同比增速 via AKShare."""
        cache_key = "sf_growth"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak
            # Try social financing flow data
            df = ak.macro_china_shrzgm()
            if df is not None and len(df) > 0:
                # Look for latest YoY growth figure
                for col in ["社会融资规模存量同比增长", "社融存量同比", "同比增长"]:
                    if col in df.columns:
                        val = float(df[col].iloc[-1])
                        self._cache_set(cache_key, val)
                        return val
        except Exception as e:
            logger.warning("AKShare social financing fetch failed: %s", e)

        # Fallback: try Guosen macro
        val = self._query_guosen("社会融资规模增速")
        if val is not None:
            self._cache_set(cache_key, val)
        return val

    def _get_m1_m2_gap(self) -> Optional[float]:
        """Fetch M1-M2剪刀差 via AKShare."""
        cache_key = "m1_m2_gap"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak
            df = ak.macro_china_money_supply()
            if df is not None and len(df) > 0:
                m1_col = None
                m2_col = None
                for col in df.columns:
                    if "m1" in col.lower() and "同比" in col:
                        m1_col = col
                    if "m2" in col.lower() and "同比" in col:
                        m2_col = col
                if m1_col and m2_col:
                    m1 = float(df[m1_col].iloc[-1])
                    m2 = float(df[m2_col].iloc[-1])
                    gap = m1 - m2
                    self._cache_set(cache_key, gap)
                    return gap
        except Exception as e:
            logger.warning("AKShare money supply fetch failed: %s", e)

        val = self._query_guosen("M1 M2 剪刀差")
        if val is not None:
            self._cache_set(cache_key, val)
        return val

    def _get_lpr_1y(self) -> Optional[float]:
        """Fetch 1Y LPR."""
        return self._get_lpr("1Y")

    def _get_lpr_5y(self) -> Optional[float]:
        """Fetch 5Y LPR."""
        return self._get_lpr("5Y")

    def _get_lpr(self, tenor: str) -> Optional[float]:
        cache_key = f"lpr_{tenor}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak
            df = ak.macro_china_lpr()
            if df is not None and len(df) > 0:
                col_map = {"1Y": ["1年期", "一年期", "LPR1Y"], "5Y": ["5年期", "五年期", "LPR5Y"]}
                for col_hint in col_map.get(tenor, []):
                    for col in df.columns:
                        if col_hint in str(col):
                            val = float(df[col].iloc[-1])
                            self._cache_set(cache_key, val)
                            return val
        except Exception as e:
            logger.warning("AKShare LPR fetch failed: %s", e)

        val = self._query_guosen(f"LPR {tenor}")
        if val is not None:
            self._cache_set(cache_key, val)
        return val

    def _get_dr007(self) -> Optional[float]:
        """Fetch DR007 (存款类机构7天质押式回购利率)."""
        cache_key = "dr007"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            import akshare as ak
            # Try bond repo rate
            df = ak.bond_repo_daily_report()
            if df is not None and len(df) > 0:
                # Look for DR007 weighted rate
                for col in df.columns:
                    if "DR007" in str(col) or "存款类机构" in str(col):
                        val = float(df[col].iloc[-1])
                        self._cache_set(cache_key, val)
                        return val
        except Exception:
            pass

        # Try alternative: SHIBOR 7-day as proxy for DR007
        try:
            import akshare as ak
            df = ak.rate_interbank()
            if df is not None and len(df) > 0:
                for col in df.columns:
                    if "7天" in str(col) or "7D" in str(col).upper():
                        val = float(df[col].iloc[-1])
                        self._cache_set(cache_key, val)
                        return val
        except Exception as e:
            logger.warning("AKShare DR007 fetch failed: %s", e)

        val = self._query_guosen("DR007 存款类机构7天质押式回购利率")
        if val is not None:
            self._cache_set(cache_key, val)
        return val

    def _query_guosen(self, query: str) -> Optional[float]:
        """Fallback: query Guosen get_macro() and attempt numeric extraction."""
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
        # Match patterns like "8.5%", "同比增长 8.5", "为 8.5"
        patterns = [
            r"([\d.]+)\s*%",  # percentage
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
