# -*- coding: utf-8 -*-
"""公司深度研究报告生成器 — 聚合护城河/红旗/DCF/管理层/研报。

使用模式:
    researcher = CompanyDeepResearcher()
    report = researcher.generate("600519", name="贵州茅台")
    print(f"综合评分: {report.overall_score:.0f}/100")
"""

from __future__ import annotations

import logging
from typing import Optional

from src.fundamental.dcf import DCFValuator
from src.fundamental.management import ManagementEvaluator
from src.fundamental.moat import MoatAnalyzer
from src.fundamental.red_flags import RedFlagDetector
from src.fundamental.report_aggregator import ReportAggregator
from src.fundamental.schema import CompanyDeepReport

logger = logging.getLogger(__name__)


class CompanyDeepResearcher:
    """公司深度研究引擎。

    综合:
      1. 护城河分析
      2. 财务红旗检测
      3. DCF 估值
      4. 管理层评估
      5. 分析师一致预期
      → 综合评分 + 投资逻辑
    """

    def __init__(self):
        self._moat = MoatAnalyzer()
        self._red_flags = RedFlagDetector()
        self._dcf = DCFValuator()
        self._management = ManagementEvaluator()
        self._reports = ReportAggregator()

    def generate(
        self,
        symbol: str,
        name: str = "",
        financials: Optional[dict] = None,
        free_cashflow: float = 0,
        current_price: float = 0,
        growth_rate: float = 0.08,
        shares_outstanding: Optional[float] = None,
        net_debt: float = 0,
    ) -> CompanyDeepReport:
        """生成公司深度研究报告。

        Args:
            symbol: 股票代码
            name: 公司名称
            financials: 财务数据 dict
            free_cashflow: 自由现金流
            current_price: 当前股价
            growth_rate: FCF 预期增长率
            shares_outstanding: 总股本
            net_debt: 净债务

        Returns:
            CompanyDeepReport
        """
        # 1. 护城河
        moat = self._moat.analyze(symbol, name)

        # 2. 红旗
        red_flags = self._red_flags.detect(symbol, name, financials)

        # 3. DCF（仅当有 FCF 数据时）
        dcf = None
        if free_cashflow > 0:
            dcf = self._dcf.valuate(
                symbol, name, free_cashflow, current_price,
                growth_rate, shares_outstanding, net_debt,
            )
        elif current_price > 0:
            dcf = self._dcf.valuate(
                symbol, name, free_cashflow=0, current_price=current_price,
            )

        # 4. 管理层
        management = self._management.evaluate(symbol, name)

        # 5. 一致预期
        consensus = self._reports.aggregate(symbol, name)

        # 6. 综合评分
        overall = self._calc_overall(moat, red_flags, dcf, management)
        thesis, risks = self._build_thesis(moat, red_flags, management)

        data_gaps = []
        if financials is None:
            data_gaps.append("[DATA_GAP] 无财务数据 — 红旗检测不完整")
        if free_cashflow <= 0:
            data_gaps.append("[DATA_GAP] 无 FCF 数据 — DCF 估值不可用")

        return CompanyDeepReport(
            symbol=symbol, name=name,
            moat=moat, red_flags=red_flags, dcf=dcf,
            management=management, consensus=consensus,
            overall_score=overall,
            confidence=self._calc_confidence(moat, red_flags, dcf, management),
            investment_thesis=thesis,
            key_risks=risks,
            data_gaps=data_gaps,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_overall(moat, red_flags, dcf, management) -> float:
        """综合评分：护城河 35% + 红旗 20% + 估值 25% + 管理层 20%。"""
        scores = []

        # 护城河 35%
        if moat:
            scores.append((moat.moat_score, 0.35))

        # 红旗 20%（无红旗 = 高分）
        if red_flags:
            rf_penalty = min(100, len(red_flags.flags) * 15)
            scores.append((100 - rf_penalty, 0.20))

        # 估值 25%
        if dcf and dcf.margin_of_safety is not None:
            # 安全边际映射到评分
            val_score = min(100, 50 + dcf.margin_of_safety * 100)
            scores.append((val_score, 0.25))
        else:
            scores.append((50, 0.25))

        # 管理层 20%
        if management:
            scores.append((management.overall_score, 0.20))

        if not scores:
            return 50.0

        total_weight = sum(w for _, w in scores)
        if total_weight <= 0:
            return 50.0

        return sum(s * w for s, w in scores) / total_weight

    @staticmethod
    def _calc_confidence(moat, red_flags, dcf, management) -> float:
        """综合置信度。"""
        confidences = []
        if moat:
            confidences.append(moat.confidence)
        if red_flags and red_flags.flags:
            confidences.append(0.7)
        if dcf and dcf.confidence:
            confidences.append(dcf.confidence)
        if management:
            confidences.append(management.confidence)
        if not confidences:
            return 0.5
        return sum(confidences) / len(confidences)

    @staticmethod
    def _build_thesis(moat, red_flags, management) -> tuple[str, list[str]]:
        """构建投资逻辑与风险。"""
        thesis_parts = []
        risks = []

        if moat:
            if moat.overall_width.value in ("wide", "dominant"):
                thesis_parts.append(f"拥有{moat.overall_width.value}护城河（{moat.moat_score:.0f}/100）")
            if moat.threats:
                risks.extend(moat.threats)

        if red_flags:
            if red_flags.critical_flags > 0:
                risks.append(f"{red_flags.critical_flags} 个严重财务红旗")
                thesis_parts.append("⚠️ 存在严重财务红旗，需深入调查")
            elif red_flags.total_flags > 0:
                risks.append(f"{red_flags.total_flags} 个财务红旗")

        if management:
            if management.overall_score >= 70:
                thesis_parts.append(f"管理层质量较好（{management.overall_score:.0f}/100）")
            elif management.overall_score < 40:
                risks.append("管理层评分偏低")

        thesis = "；".join(thesis_parts) if thesis_parts else "信息不足，无法形成投资逻辑"
        return thesis, risks
