# -*- coding: utf-8 -*-
"""CycleAnalyzer — 经济周期阶段分类 + 估值联动。

分类信号（4维）:
  1. PMI (制造业采购经理指数)
  2. 工业增加值 YoY
  3. GDP 增速 YoY
  4. PPI YoY

数据源: AKShare macro_china 系列
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from src.data.source_citation import SourceCitation, make_citation

from .schema import (
    CYCLE_SECTOR_MAP,
    CYCLE_VALUATION_ADJUSTMENT,
    CycleAnalysis,
    CyclePhase,
)

logger = logging.getLogger(__name__)


class CycleAnalyzer:
    """经济周期阶段分析器。

    使用 PMI/IP/GDP/PPI 四维信号分类五阶段。
    与 MonetaryCreditAnalyzer 协同：复用宏观象限信息丰富分类。
    """

    # PMI 阈值
    PMI_EXPANSION_LINE = 52.0   # 扩张线
    PMI_GROWTH_LINE = 50.0      # 荣枯线
    PMI_CONTRACTION_LINE = 48.0  # 收缩预警线

    # 工业增加值阈值
    IP_STRONG = 6.0    # 高增长
    IP_MODERATE = 4.0  # 中等
    IP_WEAK = 3.0      # 疲弱

    # GDP 阈值
    GDP_STRONG = 5.5
    GDP_MODERATE = 4.5

    def __init__(self):
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(hours=4)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        macro_regime: Optional[object] = None,  # MacroRegime from src.macro
        pmi: Optional[float] = None,
        industrial_production: Optional[float] = None,
        gdp_growth: Optional[float] = None,
        ppi: Optional[float] = None,
    ) -> CycleAnalysis:
        """分析当前经济周期阶段。

        Args:
            macro_regime: 已有的 MacroRegime 对象（可选，复用信用数据）
            pmi: PMI 指数
            industrial_production: 工业增加值 YoY %
            gdp_growth: GDP YoY %
            ppi: PPI YoY %
        """
        citations: list[SourceCitation] = []

        # 自动获取缺失数据
        if pmi is None:
            pmi = self._fetch_pmi()
        if pmi is not None:
            citations.append(make_citation("akshare", "pmi", "macro_indicator"))

        if industrial_production is None:
            industrial_production = self._fetch_industrial_production()
        if industrial_production is not None:
            citations.append(make_citation("akshare", "ip", "macro_indicator"))

        if gdp_growth is None:
            gdp_growth = self._fetch_gdp()
        if gdp_growth is not None:
            citations.append(make_citation("akshare", "gdp", "macro_indicator"))

        if ppi is None:
            ppi = self._fetch_ppi()
        if ppi is not None:
            citations.append(make_citation("akshare", "ppi", "macro_indicator"))

        # 信号计数
        signals = [pmi, industrial_production, gdp_growth, ppi]
        signals_available = sum(1 for s in signals if s is not None)
        confidence = self._calc_confidence(signals_available, 4)

        # PMI 趋势
        pmi_trend = self._compute_trend("pmi", pmi)

        # 分类阶段
        phase = self._classify_phase(
            pmi=pmi,
            pmi_trend=pmi_trend,
            ip=industrial_production,
            gdp=gdp_growth,
            ppi=ppi,
        )

        # 调整因子
        adj_factor = CYCLE_VALUATION_ADJUSTMENT.get(phase, 1.0)

        # 行业偏好
        pref, avoid = self._compute_sector_preferences(phase)

        # 宏观象限关联
        macro_q = None
        if macro_regime is not None:
            try:
                macro_q = getattr(macro_regime, "quadrant", None)
                if macro_q:
                    macro_q = str(macro_q)
            except Exception:
                pass

        return CycleAnalysis(
            phase=phase,
            confidence=confidence,
            pmi=pmi,
            pmi_trend=pmi_trend,
            industrial_production=industrial_production,
            gdp_growth=gdp_growth,
            ppi=ppi,
            signals_available=signals_available,
            cycle_score=self._compute_cycle_score(phase),
            cycle_adjustment_factor=adj_factor,
            valuation_ceiling_adjustment=adj_factor * 1.05,  # 天花板略高于乘数
            preferred_sectors=pref,
            avoid_sectors=avoid,
            macro_quadrant=macro_q,
            source_citations=citations,
        )

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify_phase(
        self,
        pmi: Optional[float],
        pmi_trend: str,
        ip: Optional[float],
        gdp: Optional[float],
        ppi: Optional[float],
    ) -> CyclePhase:
        """四维信号 → 周期阶段。

        优先级: PMI + trend > IP > GDP > PPI
        """
        # 默认：所有数据缺失 → TROUGH（最保守假设）
        if pmi is None:
            return CyclePhase.TROUGH

        ip = ip or 3.0
        gdp = gdp or 4.5
        ppi = ppi or 0.0

        # EXPANSION: PMI > 52, rising, strong industrial + GDP
        if pmi > self.PMI_EXPANSION_LINE and pmi_trend == "rising":
            if ip >= self.IP_STRONG and gdp >= self.GDP_STRONG:
                return CyclePhase.EXPANSION

        # 简化: PMI > 52
        if pmi > self.PMI_EXPANSION_LINE:
            if ppi > 2.0:
                return CyclePhase.PEAK
            return CyclePhase.EXPANSION

        # PEAK: PMI 50-52, falling, high PPI
        if pmi >= self.PMI_GROWTH_LINE:
            if pmi_trend == "falling":
                if ppi > 2.0:
                    return CyclePhase.PEAK
                if ip and ip < self.IP_MODERATE:
                    return CyclePhase.PEAK
            # PMI 50-52, rising → RECOVERY
            if pmi_trend == "rising":
                if ip and ip < self.IP_MODERATE:
                    return CyclePhase.RECOVERY
            return CyclePhase.EXPANSION  # PMI 50-52 stable → 偏扩张

        # RECOVERY: PMI 48-50, rising from below
        if pmi >= self.PMI_CONTRACTION_LINE:
            if pmi_trend == "rising":
                return CyclePhase.RECOVERY
            # PMI 48-50, falling → entering contraction
            if pmi_trend == "falling":
                return CyclePhase.CONTRACTION
            # PMI 48-50, stable → TROUGH
            return CyclePhase.TROUGH

        # PMI < 48
        if pmi_trend == "rising":
            return CyclePhase.TROUGH
        else:
            return CyclePhase.CONTRACTION

    def _compute_trend(self, key: str, current: Optional[float]) -> str:
        """计算指标趋势（基于缓存的前值）。"""
        if current is None:
            return "stable"

        prev_key = f"{key}_prev"
        prev = self._cache_get(prev_key)
        self._cache_set(prev_key, current)

        if prev is None:
            return "stable"

        diff = current - prev
        if abs(diff) <= 0.3:
            return "stable"
        return "rising" if diff > 0 else "falling"

    def _compute_cycle_score(self, phase: CyclePhase) -> float:
        """周期阶段 → 股票友好度评分 0-100。"""
        scores: dict[CyclePhase, float] = {
            CyclePhase.EXPANSION: 85.0,
            CyclePhase.RECOVERY: 70.0,
            CyclePhase.PEAK: 40.0,
            CyclePhase.TROUGH: 35.0,
            CyclePhase.CONTRACTION: 20.0,
        }
        return scores.get(phase, 50.0)

    def _compute_sector_preferences(
        self, phase: CyclePhase
    ) -> tuple[list[str], list[str]]:
        """获取周期阶段对应的行业偏好。"""
        entry = CYCLE_SECTOR_MAP.get(phase)
        if entry:
            return entry
        return [], []

    # ------------------------------------------------------------------
    # Data fetching (AKShare)
    # ------------------------------------------------------------------

    def _fetch_pmi(self) -> Optional[float]:
        """获取最新 PMI 值。"""
        try:
            import akshare as ak
            df = ak.macro_china_pmi()
            if df is None or df.empty:
                return None
            # 通常有两列: 日期 + PMI
            last_row = df.iloc[-1]
            for val in last_row:
                try:
                    v = float(val)
                    if 10 < v < 100:
                        return v
                except (ValueError, TypeError):
                    pass
            return None
        except Exception:
            logger.debug("PMI fetch failed", exc_info=True)
            return None

    def _fetch_industrial_production(self) -> Optional[float]:
        """获取最新工业增加值 YoY %。"""
        try:
            import akshare as ak
            df = ak.macro_china_industrial_production_yoy()
            if df is None or df.empty:
                return None
            last_row = df.iloc[-1]
            for val in last_row:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
            return None
        except Exception:
            logger.debug("IP fetch failed", exc_info=True)
            return None

    def _fetch_gdp(self) -> Optional[float]:
        """获取最新 GDP 增速 YoY %。"""
        try:
            import akshare as ak
            df = ak.macro_china_gdp_yearly()
            if df is None or df.empty:
                return None
            last_row = df.iloc[-1]
            for val in last_row:
                try:
                    v = float(val)
                    if 0 < v < 30:  # GDP 增速应该在 0-20 区间
                        return v
                except (ValueError, TypeError):
                    pass
            return None
        except Exception:
            logger.debug("GDP fetch failed", exc_info=True)
            return None

    def _fetch_ppi(self) -> Optional[float]:
        """获取最新 PPI YoY %。"""
        try:
            import akshare as ak
            df = ak.macro_china_ppi_yoy()
            if df is None or df.empty:
                return None
            last_row = df.iloc[-1]
            for val in last_row:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
            return None
        except Exception:
            logger.debug("PPI fetch failed", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Confidence
    # ------------------------------------------------------------------

    def _calc_confidence(self, signals_available: int, total: int) -> float:
        """根据可用信号数计算信心度。"""
        base = 0.90
        missing = total - signals_available
        penalty = 0.15 * missing
        return max(0.3, base - penalty)

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_get(self, key: str) -> Optional[object]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, val = entry
        if datetime.now() - ts > self._cache_ttl:
            del self._cache[key]
            return None
        return val

    def _cache_set(self, key: str, val: object):
        self._cache[key] = (datetime.now(), val)
