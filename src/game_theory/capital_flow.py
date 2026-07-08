# -*- coding: utf-8 -*-
"""资金面深度追踪 (CapitalFlowAnalyzer)。

填补原空壳实现，提供:
  1. 主力资金流向分析（超大单/大单/中单/小单）
  2. 资金-价格背离度检测
  3. 主力参与度评估

数据源: 东财 datacenter RPT_MONEYFLOW_DAILY / AKShare stock_fund_flow_individual()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# 保留原 re-export 以维持向后兼容
from .rules import TOP_3_RULES, RuleCapitalFlowModel  # noqa: F401


class DivergenceType(str, Enum):
    BULL_TRAP = "bull_trap"       # 价涨+主力流出 → 诱多出货
    BEAR_TRAP = "bear_trap"       # 价跌+主力流入 → 诱空吸筹
    TRUE_UP = "true_up"           # 价涨+主力流入 → 真实上涨
    TRUE_DOWN = "true_down"       # 价跌+主力流出 → 真实下跌
    NEUTRAL = "neutral"


@dataclass
class CapitalFlowResult:
    """资金面分析结果。"""

    symbol: str
    # 资金流向数据
    super_large_net: float = 0.0    # 超大单净流入(万元)
    large_net: float = 0.0          # 大单净流入(万元)
    medium_net: float = 0.0         # 中单净流入(万元)
    small_net: float = 0.0          # 小单净流入(万元)
    main_net: float = 0.0           # 主力净流入 = 超大单+大单(万元)
    total_turnover: float = 0.0     # 总成交额(万元)

    # 分析指标
    main_participation: float = 0.0      # 主力参与度 = 主力净额绝对值/总成交额
    main_consecutive_days: int = 0       # 主力连续流入/流出天数（正=流入，负=流出）
    divergence_type: DivergenceType = DivergenceType.NEUTRAL
    divergence_score: float = 0.0        # 资金-价格背离度 0-100

    # 操纵风险
    manipulation_risk_score: float = 0.0  # 0-100
    signals: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    # 数据质量
    data_quality: float = 0.0
    data_gaps: list[str] = field(default_factory=list)


class CapitalFlowAnalyzer:
    """资金面深度追踪分析器。

    用法:
        analyzer = CapitalFlowAnalyzer()
        result = analyzer.analyze(
            symbol="600519",
            super_large_net=5000, large_net=3000, medium_net=-2000, small_net=-6000,
            total_turnover=100000, price_change_pct=0.02,
            main_consecutive_days=3,
        )
    """

    # ── 阈值常量 ──
    MAIN_PARTICIPATION_HIGH = 0.15     # 主力参与度 > 15% → 主力高度活跃
    MAIN_PARTICIPATION_LOW = 0.03      # < 3% → 散户市
    DIVERGENCE_DAYS_THRESHOLD = 3      # 背离持续 > 3 天 → 高风险
    DIVERGENCE_SCORE_HIGH = 60         # 背离评分 > 60 → 高风险

    def analyze(
        self,
        symbol: str,
        super_large_net: float = 0.0,
        large_net: float = 0.0,
        medium_net: float = 0.0,
        small_net: float = 0.0,
        total_turnover: float = 0.0,
        price_change_pct: float = 0.0,            # 当日价格涨跌幅
        main_consecutive_days: int = 0,           # 主力连续流入天数（正）/流出天数（负）
        recent_price_trend: str = "neutral",      # "up" / "down" / "neutral"
    ) -> CapitalFlowResult:
        """执行资金面分析。"""
        result = CapitalFlowResult(
            symbol=symbol,
            super_large_net=super_large_net,
            large_net=large_net,
            medium_net=medium_net,
            small_net=small_net,
            main_net=super_large_net + large_net,
            total_turnover=total_turnover,
            main_consecutive_days=main_consecutive_days,
        )

        data_points = 0
        total_points = 4

        if total_turnover > 0:
            data_points += 1
        if abs(super_large_net) + abs(large_net) > 0:
            data_points += 1
        if abs(price_change_pct) > 0:
            data_points += 1
        if main_consecutive_days != 0:
            data_points += 1

        result.data_quality = data_points / max(total_points, 1)
        if result.data_quality < 0.5:
            result.data_gaps.append("[DATA_GAP] 资金流数据不完整")
            result.recommendations.append("资金流数据不足，降低分析权重")
            return result

        # ── 主力参与度 ──
        if total_turnover > 0:
            result.main_participation = abs(result.main_net) / total_turnover

        risk_score = 0.0

        # ── 主力参与度评估 ──
        if result.main_participation > self.MAIN_PARTICIPATION_HIGH:
            result.signals.append(
                f"主力参与度 {result.main_participation:.1%}（> {self.MAIN_PARTICIPATION_HIGH:.0%}），高度活跃"
            )
            # 可以是真趋势也可以是操纵——需要结合其他信号判断
        elif result.main_participation < self.MAIN_PARTICIPATION_LOW:
            result.signals.append(
                f"主力参与度 {result.main_participation:.1%}（< {self.MAIN_PARTICIPATION_LOW:.0%}），散户主导"
            )

        # ── 主力连续流向 ──
        if main_consecutive_days >= self.DIVERGENCE_DAYS_THRESHOLD:
            result.signals.append(f"主力连续流入 {main_consecutive_days} 天")
        elif main_consecutive_days <= -self.DIVERGENCE_DAYS_THRESHOLD:
            result.signals.append(f"主力连续流出 {abs(main_consecutive_days)} 天")

        # ── 资金-价格背离检测 ──
        divergence_score = 0.0
        # 价格涨 + 主力流出 = 诱多出货
        if price_change_pct > 0.01 and result.main_net < 0:
            divergence_score = min(100, abs(result.main_net) / max(total_turnover, 1) * 200)
            result.divergence_type = DivergenceType.BULL_TRAP
            result.signals.append(
                f"价格涨 {price_change_pct:.1%}，主力净流出 {result.main_net:.0f}万 → 诱多出货预警"
            )
            if main_consecutive_days <= -self.DIVERGENCE_DAYS_THRESHOLD:
                divergence_score += 20
                result.signals.append(f"主力连续流出 {abs(main_consecutive_days)} 天，背离加剧")
        # 价格跌 + 主力流入 = 诱空吸筹
        elif price_change_pct < -0.01 and result.main_net > 0:
            divergence_score = min(100, abs(result.main_net) / max(total_turnover, 1) * 200)
            result.divergence_type = DivergenceType.BEAR_TRAP
            result.signals.append(
                f"价格跌 {abs(price_change_pct):.1%}，主力净流入 {result.main_net:.0f}万 → 诱空吸筹预警"
            )
            if main_consecutive_days >= self.DIVERGENCE_DAYS_THRESHOLD:
                divergence_score += 20
                result.signals.append(f"主力连续流入 {main_consecutive_days} 天，吸筹确认")
        # 价涨+主力流入 = 真实上涨
        elif price_change_pct > 0.01 and result.main_net > 0:
            result.divergence_type = DivergenceType.TRUE_UP
            result.signals.append("价涨+主力流入 → 真实上涨，低操纵风险")
        # 价跌+主力流出 = 真实下跌
        elif price_change_pct < -0.01 and result.main_net < 0:
            result.divergence_type = DivergenceType.TRUE_DOWN
            result.signals.append("价跌+主力流出 → 真实下跌")

        result.divergence_score = divergence_score
        risk_score += divergence_score

        # ── 连续主力流出的操纵风险 ──
        if main_consecutive_days <= -5:
            risk_score += 25
            result.signals.append("主力连续流出超 5 天，高度警惕")
        elif main_consecutive_days <= -3:
            risk_score += 15

        result.manipulation_risk_score = min(100, risk_score)

        # ── 建议 ──
        if result.divergence_type == DivergenceType.BULL_TRAP and divergence_score > self.DIVERGENCE_SCORE_HIGH:
            result.recommendations.append("资金-价格严重背离（诱多），建议立即减仓或离场")
        elif result.divergence_type == DivergenceType.BEAR_TRAP and divergence_score > self.DIVERGENCE_SCORE_HIGH:
            result.recommendations.append("资金-价格背离（诱空），可关注但需等待价格确认")
        elif result.divergence_type == DivergenceType.TRUE_UP:
            result.recommendations.append("主力与价格方向一致，正常交易")
        elif result.divergence_type == DivergenceType.TRUE_DOWN:
            result.recommendations.append("主力与价格同步下跌，不建议抄底")

        return result


def get_capital_flow_risk(symbol: str, ctx: dict) -> float:
    """快捷函数：从上下文获取资金流操纵风险评分 0-100。"""
    analyzer = CapitalFlowAnalyzer()
    result = analyzer.analyze(
        symbol=symbol,
        super_large_net=ctx.get("super_large_net", 0.0),
        large_net=ctx.get("large_net", 0.0),
        medium_net=ctx.get("medium_net", 0.0),
        small_net=ctx.get("small_net", 0.0),
        total_turnover=ctx.get("total_turnover", 0.0),
        price_change_pct=ctx.get("price_change_pct", 0.0),
        main_consecutive_days=ctx.get("main_consecutive_days", 0),
    )
    return result.manipulation_risk_score
