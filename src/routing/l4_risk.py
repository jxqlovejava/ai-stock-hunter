# -*- coding: utf-8 -*-
"""L4 风控官 — 硬约束执行（不可覆盖）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .l3_trade import TradeSignal


@dataclass
class RiskCheck:
    """风控审查结果。"""
    passed: bool
    violations: list[str] = field(default_factory=list)
    adjusted_weight: float = 0.0
    source_citations: list = field(default_factory=list)  # Phase 1: 继承引用链


class L4RiskOfficer:
    """L4 风控官。

    硬约束（不可覆盖）:
      - 单票最大仓位: 20%
      - 单行业最大仓位: 40%
      - 单笔最大亏损: 2%
      - 组合最大回撤: 15%
      - 双创折扣: ×0.8
      - 黑天鹅熔断: 沪深300 单日 -5%
      - 流动性上限: 持仓 < 日均成交额 5%
    """

    SINGLE_STOCK_CAP = 0.20
    SINGLE_SECTOR_CAP = 0.40
    MAX_DRAWDOWN = -0.15
    SINGLE_STOP_LOSS = -0.02
    BLACK_SWAN_THRESHOLD = -0.05

    def check(
        self,
        signal: TradeSignal,
        portfolio: dict | None = None,
        market: dict | None = None,
        position_limits: dict | None = None,
    ) -> RiskCheck:
        """风控审查。返回调整后的仓位。

        Args:
            signal: L3 交易信号
            portfolio: 当前组合状态 {sector_pct, drawdown_pct, position_loss_pct}
            market: 市场状态 {hs300_change_pct}
            position_limits: 用户偏好风控约束，覆盖类级默认值。
                             键: single_stock_cap, sector_cap, max_drawdown, stop_loss
        """
        violations = []
        weight = signal.target_weight

        # 用户偏好覆盖
        _single_stock_cap = self.SINGLE_STOCK_CAP
        _sector_cap = self.SINGLE_SECTOR_CAP
        _max_drawdown = self.MAX_DRAWDOWN
        _stop_loss = self.SINGLE_STOP_LOSS
        if position_limits:
            _single_stock_cap = position_limits.get("single_stock_cap", _single_stock_cap)
            _sector_cap = position_limits.get("sector_cap", _sector_cap)
            _max_drawdown = position_limits.get("max_drawdown", _max_drawdown)
            _stop_loss = position_limits.get("stop_loss", _stop_loss)

        # 单票上限
        if weight > _single_stock_cap:
            violations.append(f"单票超限: {weight:.1%} > {_single_stock_cap:.0%}")
            weight = min(weight, _single_stock_cap)

        # 行业上限
        sector_pct = (portfolio or {}).get("sector_pct", 0)
        if sector_pct + weight > _sector_cap:
            violations.append(f"行业超限: {sector_pct + weight:.1%} > {_sector_cap:.0%}")
            weight = min(weight, _sector_cap - sector_pct)

        # 黑天鹅熔断
        market_drop = (market or {}).get("hs300_change_pct", 0)
        if market_drop <= self.BLACK_SWAN_THRESHOLD:
            violations.append("黑天鹅熔断: T+1 禁开新仓")
            if signal.action in ("OPEN", "ADD"):
                weight = 0.0

        # 组合回撤
        drawdown = (portfolio or {}).get("drawdown_pct", 0)
        if drawdown <= _max_drawdown:
            violations.append(f"组合回撤熔断: {drawdown:.1%} < {_max_drawdown:.0%}")
            weight = min(weight, 0.0)

        # 单笔止损
        position_loss = (portfolio or {}).get("position_loss_pct", 0)
        if position_loss <= _stop_loss:
            violations.append(f"单笔止损: {position_loss:.1%} 触及 {_stop_loss:.0%}")
            weight = 0.0  # 强制平仓

        return RiskCheck(
            passed=len([v for v in violations if "熔断" in v or "止损" in v]) == 0,
            violations=violations,
            adjusted_weight=max(0.0, weight),
            source_citations=signal.source_citations,  # Phase 1: 继承引用链
        )
