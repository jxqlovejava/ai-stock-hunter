"""Economic cycle & adaptive valuation framework.

Detects cycle phase (recovery/boom/recession/depression) and adapts valuation method:
  - 周期股: 席勒 PE / PB 分位 → 周期底部(高PE/低PB)=买入, 顶部(低PE/高PB)=卖出
  - 成长股: PEG = PE / earnings_growth
  - 金融股: PB × ROE framework
  - 消费股: DCF-implied fair PE from ROE and growth

Phase 5: 周期与估值框架，借鉴 financial-services sector-rotation model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CyclePhase(str, Enum):
    RECOVERY = "recovery"  # 复苏: GDP↑, inflation↓
    BOOM = "boom"  # 繁荣: GDP↑, inflation↑
    RECESSION = "recession"  # 衰退: GDP↓, inflation↑
    DEPRESSION = "depression"  # 萧条: GDP↓, inflation↓


class SectorCyclicality(str, Enum):
    CYCLICAL = "cyclical"  # 周期股
    GROWTH = "growth"  # 成长股
    DEFENSIVE = "defensive"  # 防御股
    FINANCIAL = "financial"  # 金融股


@dataclass
class CycleAnalysis:
    """Economic cycle phase assessment."""

    phase: CyclePhase = CyclePhase.RECOVERY
    confidence: float = 0.5
    gdp_growth: Optional[float] = None
    cpi: Optional[float] = None
    pmi: Optional[float] = None
    yield_curve_slope: Optional[float] = None  # 10Y-2Y spread
    sector_recommendations: dict[str, list[str]] = field(default_factory=dict)
    cycle_score: int = 50  # 0-100, higher = cycle-friendly for risk assets


@dataclass
class ValuationResult:
    """Multi-method valuation composite."""

    symbol: str = ""
    sector_cyclicality: str = "cyclical"
    cycle_phase: str = ""

    # Method-specific valuations
    shiller_pe_percentile: Optional[float] = None  # 席勒PE分位 (周期股)
    pb_percentile: Optional[float] = None  # PB分位 (周期股)
    peg_ratio: Optional[float] = None  # PEG = PE / growth (成长股)
    pb_roe_score: Optional[float] = None  # PB×ROE框架得分 (金融股)
    dcf_fair_pe: Optional[float] = None  # DCF公允PE (消费股)

    # Composite
    composite_score: int = 50  # 0-100, higher = undervalued
    valuation_signal: str = ""  # "undervalued" / "fair" / "overvalued"
    updated_at: datetime = field(default_factory=datetime.now)


# Sector → cyclicality mapping
SECTOR_CYCLICALITY_MAP: dict[str, SectorCyclicality] = {
    "钢铁": SectorCyclicality.CYCLICAL, "有色": SectorCyclicality.CYCLICAL,
    "化工": SectorCyclicality.CYCLICAL, "建材": SectorCyclicality.CYCLICAL,
    "煤炭": SectorCyclicality.CYCLICAL, "石油石化": SectorCyclicality.CYCLICAL,
    "工程机械": SectorCyclicality.CYCLICAL, "航运": SectorCyclicality.CYCLICAL,
    "新能源": SectorCyclicality.GROWTH, "半导体": SectorCyclicality.GROWTH,
    "医药": SectorCyclicality.GROWTH, "消费电子": SectorCyclicality.GROWTH,
    "军工": SectorCyclicality.GROWTH, "计算机": SectorCyclicality.GROWTH,
    "食品饮料": SectorCyclicality.DEFENSIVE, "公用事业": SectorCyclicality.DEFENSIVE,
    "农业": SectorCyclicality.DEFENSIVE, "医药商业": SectorCyclicality.DEFENSIVE,
    "银行": SectorCyclicality.FINANCIAL, "保险": SectorCyclicality.FINANCIAL,
    "券商": SectorCyclicality.FINANCIAL, "地产": SectorCyclicality.CYCLICAL,
    "消费": SectorCyclicality.DEFENSIVE, "科技": SectorCyclicality.GROWTH,
    "基建": SectorCyclicality.CYCLICAL,
}

# Cycle phase → sector recommendations
CYCLE_SECTOR_MAP: dict[CyclePhase, dict[str, list[str]]] = {
    CyclePhase.RECOVERY: {
        "recommended": ["券商", "银行", "可选消费", "科技", "地产"],
        "avoid": ["公用事业", "现金", "长债"],
    },
    CyclePhase.BOOM: {
        "recommended": ["周期", "钢铁", "有色", "煤炭", "能源", "工业"],
        "avoid": ["长债", "现金", "高估值成长"],
    },
    CyclePhase.RECESSION: {
        "recommended": ["防御性消费", "医药", "公用事业", "现金", "短债"],
        "avoid": ["周期", "券商", "地产", "高杠杆"],
    },
    CyclePhase.DEPRESSION: {
        "recommended": ["现金", "国债", "黄金", "防御性消费"],
        "avoid": ["股票", "周期", "金融", "地产"],
    },
}


class CycleAnalyzer:
    """Detect current economic cycle phase from macro indicators."""

    def __init__(self):
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(hours=4)

    def analyze(self) -> CycleAnalysis:
        """Detect current economic cycle phase."""
        gdp = self._get_gdp_growth()
        cpi = self._get_cpi()
        pmi = self._get_pmi()
        yield_slope = self._get_yield_curve_slope()

        phase, confidence, score = self._classify_phase(gdp, cpi, pmi, yield_slope)

        recs = CYCLE_SECTOR_MAP.get(phase, {})
        return CycleAnalysis(
            phase=phase,
            confidence=confidence,
            gdp_growth=gdp,
            cpi=cpi,
            pmi=pmi,
            yield_curve_slope=yield_slope,
            sector_recommendations={
                "recommended": recs.get("recommended", []),
                "avoid": recs.get("avoid", []),
            },
            cycle_score=score,
        )

    @staticmethod
    def get_sector_cyclicality(sector: str) -> SectorCyclicality:
        """Map sector name to cyclicality type."""
        return SECTOR_CYCLICALITY_MAP.get(sector, SectorCyclicality.CYCLICAL)

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_phase(
        gdp: Optional[float],
        cpi: Optional[float],
        pmi: Optional[float],
        yield_slope: Optional[float],
    ) -> tuple[CyclePhase, float, int]:
        """Classify cycle phase and compute confidence + cycle score."""
        gdp_up = gdp is not None and gdp > 3.0  # above trend
        inflation_up = cpi is not None and cpi > 2.0

        if gdp_up and not inflation_up:
            phase = CyclePhase.RECOVERY
            score = 80
        elif gdp_up and inflation_up:
            phase = CyclePhase.BOOM
            score = 70
        elif not gdp_up and inflation_up:
            phase = CyclePhase.RECESSION
            score = 30
        else:
            phase = CyclePhase.DEPRESSION
            score = 20

        # PMI adjustment
        if pmi is not None:
            if pmi > 50 and phase in (CyclePhase.RECESSION, CyclePhase.DEPRESSION):
                phase = CyclePhase.RECOVERY
                score = 60
            elif pmi < 48 and phase in (CyclePhase.BOOM, CyclePhase.RECOVERY):
                phase = CyclePhase.RECESSION
                score = 40

        # Yield curve adjustment
        if yield_slope is not None:
            if yield_slope < 0 and phase in (CyclePhase.BOOM, CyclePhase.RECOVERY):
                phase = CyclePhase.RECESSION  # inversion = recession signal
                score = 35

        signals_available = sum(1 for x in [gdp, cpi, pmi, yield_slope] if x is not None)
        confidence = min(0.9, 0.3 + signals_available * 0.15)

        return phase, confidence, score

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _get_gdp_growth(self) -> Optional[float]:
        try:
            import akshare as ak
            df = ak.macro_china_gdp()
            if df is not None and len(df) > 0:
                for col in df.columns:
                    if "同比" in str(col) or "增长" in str(col):
                        return float(df[col].iloc[-1])
        except Exception:
            pass
        return None

    def _get_cpi(self) -> Optional[float]:
        try:
            import akshare as ak
            df = ak.macro_china_cpi()
            if df is not None and len(df) > 0:
                for col in df.columns:
                    if "同比" in str(col) or "CPI" in str(col).upper():
                        return float(df[col].iloc[-1])
        except Exception:
            pass
        return None

    def _get_pmi(self) -> Optional[float]:
        try:
            import akshare as ak
            df = ak.macro_china_pmi()
            if df is not None and len(df) > 0:
                for col in df.columns:
                    if "制造业" in str(col) and ("指数" in str(col) or "PMI" in str(col)):
                        return float(df[col].iloc[-1])
        except Exception:
            pass
        return None

    def _get_yield_curve_slope(self) -> Optional[float]:
        try:
            import akshare as ak
            df = ak.bond_china_yield()
            if df is not None and len(df) > 0:
                y10 = y2 = None
                for col in df.columns:
                    if "10年" in str(col) or "10Y" in str(col):
                        y10 = float(df[col].iloc[-1])
                    if "2年" in str(col) or "2Y" in str(col):
                        y2 = float(df[col].iloc[-1])
                if y10 and y2:
                    return y10 - y2
        except Exception:
            pass
        return None


class ValuationAnalyzer:
    """Adaptive valuation: applies different methods based on sector cyclicality."""

    def __init__(self):
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(hours=6)

    def analyze(
        self, symbol: str, quote: dict, cycle: Optional[CycleAnalysis] = None
    ) -> ValuationResult:
        """Compute valuation using method adapted to sector cyclicality."""
        result = ValuationResult(symbol=symbol)

        sector = quote.get("sector", "周期")
        cyclicality = CycleAnalyzer.get_sector_cyclicality(sector)
        result.sector_cyclicality = cyclicality.value
        result.cycle_phase = cycle.phase.value if cycle else "unknown"

        pe = quote.get("pe_ttm") or quote.get("pe", 0) or 0
        pb = quote.get("pb", 0) or 0
        roe = quote.get("roe", 0) or 0

        if cyclicality == SectorCyclicality.CYCLICAL:
            # PB percentile: low PB = cheap (buy at cycle bottom)
            result.pb_percentile = self._compute_pb_percentile(symbol, pb)
            result.shiller_pe_percentile = self._compute_shiller_pe_percentile(symbol, pe)
            score = self._score_cyclical(result, cycle)
        elif cyclicality == SectorCyclicality.GROWTH:
            # PEG: PE / earnings growth → <1 = undervalued
            growth = quote.get("earnings_growth_yoy", 10) or 10
            result.peg_ratio = round(pe / max(growth, 0.1), 2) if pe > 0 else None
            score = self._score_growth(result)
        elif cyclicality == SectorCyclicality.FINANCIAL:
            # PB × ROE framework
            if pb > 0 and roe > 0:
                result.pb_roe_score = round(roe / pb * 10, 2)
            score = self._score_financial(result)
        else:
            # Defensive: DCF-implied fair PE from ROE
            if roe > 0:
                result.dcf_fair_pe = round(roe * 100 / 8, 2)  # 8% cost of equity
            score = self._score_defensive(result, pe)

        result.composite_score = score
        result.valuation_signal = self._classify_signal(score, cycle)

        return result

    def _score_cyclical(self, r: ValuationResult, cycle: Optional[CycleAnalysis]) -> int:
        """周期股: 高PE/低PB=周期底部→买入, 低PE/高PB=周期顶部→卖出."""
        score = 50
        if r.pb_percentile is not None:
            if r.pb_percentile < 20:
                score += 25  # deep value
            elif r.pb_percentile < 40:
                score += 10
            elif r.pb_percentile > 80:
                score -= 25
            elif r.pb_percentile > 60:
                score -= 10
        if cycle and cycle.phase in (CyclePhase.DEPRESSION, CyclePhase.RECESSION):
            score += 10  # cyclical stocks cheaper at cycle bottoms
        return max(0, min(100, score))

    def _score_growth(self, r: ValuationResult) -> int:
        """成长股: PEG < 1 = undervalued."""
        score = 50
        if r.peg_ratio is not None:
            if r.peg_ratio < 0.5:
                score += 30
            elif r.peg_ratio < 1.0:
                score += 15
            elif r.peg_ratio > 2.5:
                score -= 30
            elif r.peg_ratio > 1.5:
                score -= 15
        return max(0, min(100, score))

    def _score_financial(self, r: ValuationResult) -> int:
        """金融股: PB×ROE > threshold = undervalued."""
        score = 50
        if r.pb_roe_score is not None:
            if r.pb_roe_score > 15:
                score += 25
            elif r.pb_roe_score > 10:
                score += 10
            elif r.pb_roe_score < 5:
                score -= 20
        return max(0, min(100, score))

    def _score_defensive(self, r: ValuationResult, pe: float) -> int:
        """防御股: PE < DCF公允PE = undervalued."""
        score = 50
        if r.dcf_fair_pe and r.dcf_fair_pe > 0 and pe > 0:
            ratio = pe / r.dcf_fair_pe
            if ratio < 0.7:
                score += 20
            elif ratio < 1.0:
                score += 5
            elif ratio > 1.5:
                score -= 20
        return max(0, min(100, score))

    @staticmethod
    def _classify_signal(score: int, cycle: Optional[CycleAnalysis]) -> str:
        if score >= 75:
            return "undervalued"
        elif score >= 40:
            return "fair"
        return "overvalued"

    @staticmethod
    def _compute_pb_percentile(symbol: str, pb: float) -> Optional[float]:
        """Estimate PB percentile from historical data (stub)."""
        if pb <= 0:
            return None
        # ponytail: rough heuristic based on sector PB range
        if pb < 1.0:
            return 15.0
        elif pb < 1.5:
            return 35.0
        elif pb < 2.5:
            return 55.0
        elif pb < 4.0:
            return 75.0
        return 90.0

    @staticmethod
    def _compute_shiller_pe_percentile(symbol: str, pe: float) -> Optional[float]:
        """Estimate Shiller PE percentile (stub — needs 10y earnings history)."""
        if pe <= 0:
            return 100.0
        if pe < 10:
            return 10.0
        elif pe < 20:
            return 35.0
        elif pe < 30:
            return 60.0
        elif pe < 50:
            return 80.0
        return 95.0

    def cache_clear(self) -> None:
        self._cache.clear()
