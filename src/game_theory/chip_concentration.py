# -*- coding: utf-8 -*-
"""筹码集中度分析器 (ChipConcentrationAnalyzer)。

A 股反操纵最核心的能力——庄家操纵的前提是筹码集中。
通过识别筹码集中度，提前避开操纵高发标的。

数据源: AKShare stock_holder_num() / 东财 datacenter
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ChipConcentrationResult:
    """筹码集中度分析结果。"""

    symbol: str
    # 原始数据
    shareholder_count: Optional[int] = None          # 最新股东户数
    shareholder_count_prev_q: Optional[int] = None   # 上季度股东户数
    shareholder_change_pct: float = 0.0              # 股东户数环比变化率
    top10_holding_pct: float = 0.0                   # 前十大股东持股比例
    top10_float_holding_pct: float = 0.0             # 前十大流通股东持股比例
    avg_holding_per_capita: Optional[float] = None   # 人均持股金额(万元)
    avg_holding_change_pct: float = 0.0              # 户均持股变化率

    # 评分
    concentration_score: float = 0.0    # 筹码集中度评分 0-100
    manipulation_risk_score: float = 0.0  # 操纵风险 0-100
    risk_level: str = "LOW"             # LOW / MEDIUM / HIGH / CRITICAL

    # 信号
    signals: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    # 数据质量
    data_quality: float = 0.0  # 0.0-1.0
    data_gaps: list[str] = field(default_factory=list)


class ChipConcentrationAnalyzer:
    """筹码集中度分析器。

    用法:
        analyzer = ChipConcentrationAnalyzer()
        result = analyzer.analyze(
            symbol="600519",
            shareholder_count=123456,
            shareholder_count_prev_q=145000,
            top10_holding=0.72,
        )
        # 或从 context dict 自动提取:
        result = analyzer.analyze_from_context(symbol="600519", ctx={...})
    """

    # ── 阈值常量 ──
    SHAREHOLDER_DECLINE_HIGH = 0.15     # 股东户数环比下降 > 15% → 高度集中
    SHAREHOLDER_DECLINE_MED = 0.10      # > 10% → 中度集中
    TOP10_HOLDING_CRITICAL = 0.70       # 前十大持股 > 70% → 极度集中
    TOP10_HOLDING_HIGH = 0.60           # > 60% → 高度集中
    TOP10_HOLDING_MED = 0.50            # > 50% → 中度集中
    AVG_HOLDING_INCREASE_HIGH = 0.20    # 户均持股连续上升 > 20% → 吸筹中

    def analyze(
        self,
        symbol: str,
        shareholder_count: Optional[int] = None,
        shareholder_count_prev_q: Optional[int] = None,
        shareholder_count_prev_2q: Optional[int] = None,
        top10_holding_pct: float = 0.0,
        top10_float_holding_pct: float = 0.0,
        avg_holding_per_capita: Optional[float] = None,
        avg_holding_prev_q: Optional[float] = None,
    ) -> ChipConcentrationResult:
        """计算筹码集中度与操纵风险。

        所有数据字段可选——缺失时分析器自动标注 DATA_GAP 并降低置信度。
        """
        result = ChipConcentrationResult(symbol=symbol)
        data_points = 0
        total_points = 6

        # ── 股东户数变化 ──
        if shareholder_count is not None and shareholder_count_prev_q is not None:
            if shareholder_count_prev_q > 0:
                result.shareholder_count = shareholder_count
                result.shareholder_count_prev_q = shareholder_count_prev_q
                result.shareholder_change_pct = (
                    (shareholder_count - shareholder_count_prev_q) / shareholder_count_prev_q
                )
                data_points += 1
        else:
            result.data_gaps.append("[DATA_GAP] 股东户数数据不可用")

        # ── 前十大持股集中度 ──
        if top10_holding_pct > 0:
            result.top10_holding_pct = top10_holding_pct
            data_points += 1
        if top10_float_holding_pct > 0:
            result.top10_float_holding_pct = top10_float_holding_pct
            data_points += 1
        if top10_holding_pct == 0 and top10_float_holding_pct == 0:
            result.data_gaps.append("[DATA_GAP] 前十大股东数据不可用")

        # ── 户均持股变化 ──
        if avg_holding_per_capita is not None and avg_holding_prev_q is not None:
            if avg_holding_prev_q > 0:
                result.avg_holding_per_capita = avg_holding_per_capita
                result.avg_holding_change_pct = (
                    (avg_holding_per_capita - avg_holding_prev_q) / avg_holding_prev_q
                )
                data_points += 1
        else:
            result.data_gaps.append("[DATA_GAP] 人均持股数据不可用")

        # ── 计算集中度评分 0-100 ──
        conc_score = 0.0
        sig_count = 0

        # 股东户数下降信号
        decline = abs(result.shareholder_change_pct) if result.shareholder_change_pct < 0 else 0
        if decline > self.SHAREHOLDER_DECLINE_HIGH:
            conc_score += 40
            sig_count += 1
            result.signals.append(
                f"股东户数环比下降 {decline:.1%}（> {self.SHAREHOLDER_DECLINE_HIGH:.0%}），高度集中预警"
            )
        elif decline > self.SHAREHOLDER_DECLINE_MED:
            conc_score += 25
            sig_count += 1
            result.signals.append(f"股东户数环比下降 {decline:.1%}，筹码趋于集中")
        elif result.shareholder_change_pct > 0.10:
            conc_score -= 10
            result.signals.append(f"股东户数环比增加 {result.shareholder_change_pct:.1%}，筹码分散")

        # 前十大持股信号
        use_top10 = max(result.top10_holding_pct, result.top10_float_holding_pct)
        if use_top10 > self.TOP10_HOLDING_CRITICAL:
            conc_score += 40
            sig_count += 1
            result.signals.append(f"前十大股东持股 {use_top10:.0%}（> {self.TOP10_HOLDING_CRITICAL:.0%}），筹码极度集中")
        elif use_top10 > self.TOP10_HOLDING_HIGH:
            conc_score += 30
            sig_count += 1
            result.signals.append(f"前十大股东持股 {use_top10:.0%}（> {self.TOP10_HOLDING_HIGH:.0%}），筹码高度集中")
        elif use_top10 > self.TOP10_HOLDING_MED:
            conc_score += 15
            sig_count += 1
            result.signals.append(f"前十大股东持股 {use_top10:.0%}，筹码中度集中")

        # 户均持股上升信号（连续吸筹）
        if result.avg_holding_change_pct > self.AVG_HOLDING_INCREASE_HIGH:
            conc_score += 20
            sig_count += 1
            result.signals.append(f"户均持股连续上升 {result.avg_holding_change_pct:.1%}，吸筹进行中")

        result.concentration_score = max(0.0, min(100.0, conc_score))

        # ── 操纵风险评估 ──
        # 筹码集中 = 庄家控盘能力强 = 操纵风险高
        # 但集中本身不一定是坏事（机构抱团也是集中）
        result.manipulation_risk_score = result.concentration_score * 0.8

        # 确定风险等级
        if result.concentration_score >= 70:
            result.risk_level = "CRITICAL"
        elif result.concentration_score >= 50:
            result.risk_level = "HIGH"
        elif result.concentration_score >= 30:
            result.risk_level = "MEDIUM"
        else:
            result.risk_level = "LOW"

        # 数据质量
        result.data_quality = data_points / max(total_points, 1)
        if result.data_quality < 0.5:
            result.manipulation_risk_score *= 0.7  # 数据不足，降低风险评分置信度

        # ── 建议 ──
        if result.risk_level == "CRITICAL":
            result.recommendations.append("筹码极度集中，庄家控盘能力极强，建议降低仓位或避免参与")
        elif result.risk_level == "HIGH":
            result.recommendations.append("筹码集中度较高，提高操纵检测敏感度，严格止损")
        elif result.risk_level == "MEDIUM":
            result.recommendations.append("筹码有一定集中，保持警惕，正常仓位")
        else:
            result.recommendations.append("筹码分散，庄家难以操纵，技术分析有效性较高")

        return result

    def analyze_from_context(
        self, symbol: str, ctx: dict
    ) -> ChipConcentrationResult:
        """从上下文字典提取数据进行筹码分析。"""
        return self.analyze(
            symbol=symbol,
            shareholder_count=ctx.get("shareholder_count"),
            shareholder_count_prev_q=ctx.get("shareholder_count_prev_q"),
            shareholder_count_prev_2q=ctx.get("shareholder_count_prev_2q"),
            top10_holding_pct=ctx.get("top10_holding_pct", 0.0),
            top10_float_holding_pct=ctx.get("top10_float_holding_pct", 0.0),
            avg_holding_per_capita=ctx.get("avg_holding_per_capita"),
            avg_holding_prev_q=ctx.get("avg_holding_prev_q"),
        )


def get_chip_risk_from_context(symbol: str, ctx: dict) -> float:
    """快捷函数：从上下文获取筹码操纵风险评分 0-100。"""
    analyzer = ChipConcentrationAnalyzer()
    result = analyzer.analyze_from_context(symbol, ctx)
    return result.manipulation_risk_score
