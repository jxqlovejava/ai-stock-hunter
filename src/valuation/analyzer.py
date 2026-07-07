# -*- coding: utf-8 -*-
"""ValuationAnalyzer — 多维估值评分引擎。

子维度（5项，权重可配置）:
  1. PE 分位评分 (0.30): 低分位→便宜→高分
  2. 行业相对估值 (0.25): PE vs 行业中位数
  3. PB-ROE 匹配 (0.20): 实际 PB vs 合理 PB
  4. PEG (0.15): PE / 盈利增速
  5. 股息率 (0.10): 高股息→加分
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from src.data.source_citation import SourceCitation, make_citation

from .schema import ValuationPhase, ValuationResult, ValuationSubScores

logger = logging.getLogger(__name__)


@dataclass
class _ValuationWeights:
    """估值子维度权重配置。"""

    pe_percentile: float = 0.30
    industry_relative: float = 0.25
    pb_roe_match: float = 0.20
    peg: float = 0.15
    dividend_yield: float = 0.10

    @property
    def total(self) -> float:
        return (
            self.pe_percentile
            + self.industry_relative
            + self.pb_roe_match
            + self.peg
            + self.dividend_yield
        )

    def normalize(self) -> "_ValuationWeights":
        """归一化到总和 1.0。"""
        t = self.total
        if abs(t - 1.0) < 1e-6:
            return self
        return _ValuationWeights(
            pe_percentile=self.pe_percentile / t,
            industry_relative=self.industry_relative / t,
            pb_roe_match=self.pb_roe_match / t,
            peg=self.peg / t,
            dividend_yield=self.dividend_yield / t,
        )


class ValuationAnalyzer:
    """多维估值分析器。

    支持从 Quote/FundamentalMetrics 自动计算，也可接受外部预先计算的值。
    """

    # PE 分位阈值
    DEEP_VALUE_PE_PCT = 20
    PREMIUM_PE_PCT = 60
    BUBBLE_PE_PCT = 80

    # PB-ROE 模型默认参数
    DEFAULT_COST_OF_EQUITY = 0.10  # A股平均股权成本 10%

    def __init__(self, weights: Optional[_ValuationWeights] = None):
        self.weights = weights or _ValuationWeights()
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._cache_ttl = timedelta(minutes=30)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        symbol: str,
        name: str,
        pe_ttm: Optional[float] = None,
        pb: Optional[float] = None,
        pe_percentile: Optional[float] = None,
        pb_percentile: Optional[float] = None,
        roe: Optional[float] = None,
        earnings_growth: Optional[float] = None,
        dividend_yield: Optional[float] = None,
        industry_pe_median: Optional[float] = None,
        industry_pb_median: Optional[float] = None,
    ) -> ValuationResult:
        """执行多维估值分析。

        Args:
            symbol: 股票代码
            name: 股票名称
            pe_ttm: 滚动市盈率
            pb: 市净率
            pe_percentile: PE 在全市场分位数 0-100
            pb_percentile: PB 分位数
            roe: 净资产收益率 %
            earnings_growth: 净利润 YoY 增速 %
            dividend_yield: 股息率 %
            industry_pe_median: 行业 PE 中位数
            industry_pb_median: 行业 PB 中位数
        """
        citations: list[SourceCitation] = []

        # --- 1. PE 分位评分 ---
        pe_score = self._score_pe_percentile(pe_percentile, pe_ttm)
        if pe_percentile is not None:
            citations.append(make_citation("tencent", "pe_percentile", "factor", nature="interpretation"))

        # --- 2. 行业相对估值 ---
        ind_score = self._score_industry_relative(pe_ttm, industry_pe_median)
        if industry_pe_median is not None:
            citations.append(make_citation("akshare", "industry_pe", "industry_pe", nature="fact"))

        # --- 3. PB-ROE 匹配 ---
        pb_roe_score, pb_justified = self._score_pb_roe(pb, roe)
        if pb is not None and roe is not None:
            citations.append(make_citation("tencent", "pb_roe", "fundamental", nature="interpretation"))

        # --- 4. PEG ---
        peg_score, peg_ratio = self._score_peg(pe_ttm, earnings_growth)
        if pe_ttm is not None and earnings_growth is not None:
            citations.append(make_citation("tencent", "peg", "fundamental", nature="interpretation"))

        # --- 5. 股息率 ---
        div_score = self._score_dividend_yield(dividend_yield)
        if dividend_yield is not None:
            citations.append(make_citation("akshare", "dividend_yield", "dividend_yield"))

        # --- 合成 ---
        signals = [
            bool(pe_percentile is not None),
            bool(industry_pe_median is not None or pe_ttm is not None),
            bool(pb is not None and roe is not None),
            bool(pe_ttm is not None and earnings_growth is not None),
            bool(dividend_yield is not None),
        ]
        signals_available = sum(signals)
        sub_confidence = self._calc_sub_confidence(signals_available, 5)

        sub_scores = ValuationSubScores(
            pe_percentile_score=pe_score,
            pb_percentile_score=self._score_pe_percentile(pb_percentile),  # PB 分位同理
            peg_score=peg_score,
            industry_relative_score=ind_score,
            pb_roe_match_score=pb_roe_score,
            dividend_yield_score=div_score,
            signals_available=signals_available,
            confidence=sub_confidence,
        )

        w = self.weights.normalize()
        composite = (
            pe_score * w.pe_percentile
            + ind_score * w.industry_relative
            + pb_roe_score * w.pb_roe_match
            + peg_score * w.peg
            + div_score * w.dividend_yield
        )

        phase = self._classify_phase(composite, pe_percentile, pb, pb_percentile)

        return ValuationResult(
            symbol=symbol,
            name=name,
            composite_score=round(max(0, min(100, composite)), 1),
            sub_scores=sub_scores,
            phase=phase,
            pe_ttm=pe_ttm,
            pb=pb,
            pe_percentile=pe_percentile,
            pb_percentile=pb_percentile,
            pb_justified=pb_justified,
            industry_pe_median=industry_pe_median,
            industry_pb_median=industry_pb_median,
            peg_ratio=peg_ratio,
            dividend_yield=dividend_yield,
            source_citations=citations,
        )

    # ------------------------------------------------------------------
    # Sub-dimension scoring methods
    # ------------------------------------------------------------------

    def _score_pe_percentile(self, pe_percentile: Optional[float], pe_ttm: Optional[float] = None) -> float:
        """PE 分位评分: 低分位=便宜=高分。

        pe_percentile 10 → 90分, 50 → 50分, 90 → 10分
        无分位数据时用 PE_TTM 绝对值估算: <15=便宜(80), >50=昂贵(20)
        """
        if pe_percentile is not None:
            return max(0.0, min(100.0, 100.0 - pe_percentile))
        # Fallback: 用 PE_TTM 绝对值粗略估算
        if pe_ttm is not None and pe_ttm > 0:
            if pe_ttm < 15:
                return 80.0
            elif pe_ttm < 25:
                return 65.0
            elif pe_ttm < 40:
                return 50.0
            elif pe_ttm < 60:
                return 35.0
            elif pe_ttm < 100:
                return 20.0
            else:
                return 10.0
        return 50.0

    def _score_industry_relative(
        self,
        stock_pe: Optional[float],
        industry_pe_median: Optional[float],
    ) -> float:
        """行业相对估值评分。

        股票 PE 低于行业中位数 → 高分，高于 → 低分。
        无行业数据时返回 50。
        """
        if stock_pe is None or industry_pe_median is None:
            return 50.0
        if industry_pe_median <= 0 or stock_pe <= 0:
            return 50.0

        # 相对折溢价
        discount = (industry_pe_median - stock_pe) / max(stock_pe, industry_pe_median)
        score = 50.0 + discount * 50.0  # 0-100
        return max(0.0, min(100.0, score))

    def _score_pb_roe(
        self,
        pb: Optional[float],
        roe: Optional[float],
        cost_of_equity: float = DEFAULT_COST_OF_EQUITY,
    ) -> tuple[float, Optional[float]]:
        """PB-ROE 匹配评分。

        justified_pb = ROE / cost_of_equity
        实际 PB 接近合理 PB → 高分。
        Returns: (score, justified_pb)
        """
        if pb is None or roe is None or roe <= 0:
            return 50.0, None
        if pb <= 0:
            return 50.0, None

        roe_pct = roe / 100.0 if roe > 1 else roe  # 统一转为小数
        justified = roe_pct / cost_of_equity

        if justified <= 0:
            return 50.0, round(justified, 2)

        # 偏离度: |actual - justified| / justified
        deviation = abs(pb - justified) / justified
        if deviation <= 0.15:
            score = 85.0  # 接近合理值
        elif deviation <= 0.30:
            score = 70.0
        elif deviation <= 0.50:
            deviation_score = 50.0 - (deviation - 0.30) / 0.20 * 20.0
            score = max(30.0, deviation_score)
        elif deviation <= 1.0:
            deviation_score = 30.0 - (deviation - 0.50) / 0.50 * 20.0
            score = max(10.0, deviation_score)
        else:
            score = 10.0

        # 低估加分: actual_PB < justified_PB
        if pb < justified:
            score = min(100.0, score + 10.0)

        return round(score, 1), round(justified, 2)

    def _score_peg(
        self,
        pe_ttm: Optional[float],
        earnings_growth: Optional[float],
    ) -> tuple[float, Optional[float]]:
        """PEG 评分。

        PEG < 1: 低估 → 高分
        PEG 1-2: 合理 → 50-70
        PEG > 2: 高估 → 低分
        无增速/负增速 → 50
        """
        if pe_ttm is None or earnings_growth is None:
            return 50.0, None
        if pe_ttm <= 0 or earnings_growth <= 0:
            return 50.0, None

        peg = pe_ttm / earnings_growth

        if peg <= 0.5:
            score = 95.0
        elif peg <= 1.0:
            score = 85.0 - (peg - 0.5) / 0.5 * 15.0
        elif peg <= 2.0:
            score = 70.0 - (peg - 1.0) / 1.0 * 20.0
        elif peg <= 3.0:
            score = 50.0 - (peg - 2.0) / 1.0 * 20.0
        else:
            score = 30.0 - min(20.0, (peg - 3.0) / 3.0 * 20.0)

        return round(max(5.0, score), 1), round(peg, 2)

    def _score_dividend_yield(self, dividend_yield: Optional[float]) -> float:
        """股息率评分。

        > 3%: 80
        1-3%: 60
        0.5-1%: 50
        < 0.5%: 40
        无分红: 40
        """
        if dividend_yield is None:
            return 40.0

        if dividend_yield >= 4.0:
            return 85.0
        elif dividend_yield >= 3.0:
            return 80.0
        elif dividend_yield >= 2.0:
            return 70.0
        elif dividend_yield >= 1.0:
            return 60.0
        elif dividend_yield >= 0.5:
            return 50.0
        else:
            return 40.0

    # ------------------------------------------------------------------
    # Phase classification
    # ------------------------------------------------------------------

    def _classify_phase(
        self,
        composite_score: float,
        pe_percentile: Optional[float] = None,
        pb: Optional[float] = None,
        pb_percentile: Optional[float] = None,
    ) -> ValuationPhase:
        """根据综合评分和分位数据分类估值阶段。"""
        # PE 分位优先判断
        if pe_percentile is not None:
            if pe_percentile <= self.DEEP_VALUE_PE_PCT:
                return ValuationPhase.DEEP_VALUE
            elif pe_percentile >= self.BUBBLE_PE_PCT and pb is not None and pb > 5:
                return ValuationPhase.BUBBLE
            elif pe_percentile >= self.PREMIUM_PE_PCT:
                return ValuationPhase.PREMIUM

        # 综合评分回退
        if composite_score >= 70:
            return ValuationPhase.DEEP_VALUE
        elif composite_score <= 20:
            return ValuationPhase.BUBBLE
        elif composite_score <= 35:
            return ValuationPhase.PREMIUM

        return ValuationPhase.FAIR_VALUE

    # ------------------------------------------------------------------
    # Confidence
    # ------------------------------------------------------------------

    def _calc_sub_confidence(self, signals_available: int, total: int) -> float:
        """根据可用信号数计算子维度信心度。

        每缺一个信号扣 0.15。
        """
        base = 0.95
        missing = total - signals_available
        penalty = 0.15 * missing
        return max(0.3, base - penalty)
