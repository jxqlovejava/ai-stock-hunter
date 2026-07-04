# -*- coding: utf-8 -*-
"""L1 分析师 — 多维扫描（量化为主，AI 为辅）。

分析维度:
  1. 宏观环境打分
  2. 量化因子扫描 (价值/质量/动量)
  3. 物理瓶颈分析 (借鉴 cyberagent: 供应链定位 + 瓶颈分类)
  4. 情绪信号检测
  5. 多空双视角
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.industry.bottleneck import BottleneckAnalysis, BottleneckType
from src.industry.supply_chain import classify_stock


@dataclass
class AnalysisReport:
    """L1 分析报告。"""
    symbol: str
    name: str
    macro_score: float = 50.0
    value_score: float = 50.0
    quality_score: float = 50.0
    momentum_score: float = 50.0
    bottleneck_analysis: Optional[BottleneckAnalysis] = None  # cyberagent 瓶颈分析
    sentiment_signal: str = "NEUTRAL"
    bull_case: str = ""
    bear_case: str = ""
    bottlenecks: list[str] = field(default_factory=list)
    upstream_risks: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


class L1Analyzer:
    """L1 分析师: 5 个分析维度。"""

    def analyze(
        self,
        symbol: str,
        name: str,
        quote: Optional[dict] = None,
        financials: Optional[list] = None,
        macro: Optional[dict] = None,
        sentiment: Optional[dict] = None,
    ) -> AnalysisReport:
        report = AnalysisReport(symbol=symbol, name=name)

        if macro:
            report.macro_score = self._score_macro(macro)

        if quote and financials:
            report.value_score = self._score_value(quote)
            report.quality_score = self._score_quality(financials)
            report.momentum_score = self._score_momentum(quote)

        # 🆕 物理瓶颈分析 (借鉴 cyberagent)
        report.bottleneck_analysis = self._analyze_bottleneck(symbol, name)

        if sentiment:
            report.sentiment_signal = sentiment.get("level", "NEUTRAL")

        report.bull_case = self._bull_case(name, quote, financials)
        report.bear_case = self._bear_case(name, quote, financials)
        return report

    def _analyze_bottleneck(self, symbol: str, name: str) -> Optional[BottleneckAnalysis]:
        node = classify_stock(symbol)
        if node is None:
            return None
        analysis = BottleneckAnalysis(
            symbol=symbol, name=name,
            core_business=node.description,
            supply_chain_layer=node.layer,
            bottleneck_type=node.bottleneck_type,
            constraint_description=node.constraint or "",
        )
        score_map = {
            BottleneckType.OWNER: 100, BottleneckType.ADJACENT: 65,
            BottleneckType.DERIVATIVE: 35, BottleneckType.NONE: 10,
        }
        analysis.bottleneck_score = score_map.get(node.bottleneck_type, 0)
        return analysis

    def _score_macro(self, macro: dict) -> float:
        score = 50.0
        pmi = macro.get("pmi", 50)
        score += (pmi - 50) * 1.0
        erp = macro.get("erp", 4.0)
        score += (erp - 4.0) * 2.5
        return max(0, min(100, score))

    def _score_value(self, quote: dict) -> float:
        pe_pct = quote.get("pe_percentile", 50)
        return max(0, min(100, 100 - pe_pct))

    def _score_quality(self, financials: list) -> float:
        if not financials:
            return 50.0
        roe = financials[-1].get("roe", 10) if isinstance(financials[-1], dict) else 10
        return max(0, min(100, roe * 4))

    def _score_momentum(self, quote: dict) -> float:
        nb = quote.get("northbound", 0)
        return 50.0 + min(max(nb * 10, -30), 30)

    def _bull_case(self, name: str, quote: dict | None, fin: list | None) -> str:
        return f"{name}: 估值合理 + ROE稳定 + 北向资金关注"

    def _bear_case(self, name: str, quote: dict | None, fin: list | None) -> str:
        return f"{name}: 宏观不确定性 + 行业竞争加剧 + 流动性风险"
