# -*- coding: utf-8 -*-
"""L4 风控官 — 硬约束执行（不可覆盖）。Phase 4: Alpha 衰减风控。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from .l3_trade import TradeSignal

logger = logging.getLogger(__name__)


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
    # Phase 4: Alpha 衰减阈值
    ALPHA_DECAY_WARN_DAYS = 30          # Alpha 30 天未更新 → 警告
    ALPHA_CROWDED_WEIGHT_CUT = 0.5      # 拥挤时仓位减半

    def _check_alpha_decay(
        self,
        signal: TradeSignal,
        portfolio: dict,
    ) -> list[str]:
        """Phase 4: Alpha 衰减风控检查。

        检查项:
          1. Alpha 衰减速度过快 → 减仓提醒
          2. 叙事阶段迁移 → 调整建议
          3. 讨论量暴涨 + 逻辑无更新 → 拥挤警告

        Returns:
            violations list (可能包含 ALPHA_DECAY / ALPHA_CROWDED 标记)
        """
        violations: list[str] = []

        # 从 portfolio 中获取 Alpha 追踪信息
        alpha_tracker = portfolio.get("alpha_tracker", {})

        # 1. Alpha 衰减速度检查
        decay_velocity = alpha_tracker.get("decay_velocity", 0.0)
        if decay_velocity > 1.0:
            violations.append(
                f"ALPHA_DECAY: Alpha 快速衰减 ({decay_velocity:.1f}/天), 建议减仓"
            )
        elif decay_velocity > 0.3:
            violations.append(
                f"ALPHA_AGING: Alpha 正在衰减 ({decay_velocity:.1f}/天)"
            )

        # 2. Alpha 衰减天数检查
        days_since = alpha_tracker.get("days_since_detection", 0)
        if days_since > self.ALPHA_DECAY_WARN_DAYS:
            violations.append(
                f"ALPHA_STALE: Alpha 信号 {days_since} 天未更新，可能已失效"
            )

        # 3. 拥挤检查
        is_crowded = alpha_tracker.get("is_crowded", False)
        if is_crowded:
            violations.append(
                "ALPHA_CROWDED: Alpha 已被拥挤挤出，建议清仓或大幅减仓"
            )

        # 4. 叙事阶段迁移检查
        narrative_stage = alpha_tracker.get("narrative_stage", "")
        if narrative_stage in ("consensus", "crowded"):
            violations.append(
                f"ALPHA_STAGE_SHIFT: 叙事进入 {narrative_stage} 阶段, "
                "Alpha 空间显著收窄"
            )
            if narrative_stage == "crowded":
                violations.append("ALPHA_EXIT: 叙事拥挤，建议清仓离场")

        if violations:
            logger.info(
                "Alpha decay risk for %s: %s",
                signal.symbol,
                "; ".join(violations),
            )

        return violations

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

        # Phase 4: Alpha 衰减风控检查
        alpha_violations = self._check_alpha_decay(signal, portfolio or {})
        violations.extend(alpha_violations)
        if any("清仓" in v for v in alpha_violations):
            weight = min(weight, 0.0)

        # Auto-blacklist check
        blacklist_violations = self._check_blacklist(signal.symbol, signal.name, quote_data=signal.extra or {})
        violations.extend(blacklist_violations)
        if any("黑名单" in v for v in blacklist_violations):
            weight = 0.0

        return RiskCheck(
            passed=len([v for v in violations if "熔断" in v or "止损" in v or "黑名单" in v]) == 0,
            violations=violations,
            adjusted_weight=max(0.0, weight),
            source_citations=signal.source_citations,  # Phase 1: 继承引用链
        )

    # ------------------------------------------------------------------
    # Auto-blacklist
    # ------------------------------------------------------------------

    # Static blacklist (manually maintained)
    STATIC_BLACKLIST: set[str] = set()  # e.g., known fraud, delisting risk

    @classmethod
    def add_to_blacklist(cls, symbol: str) -> None:
        """Manually add a symbol to the static blacklist."""
        cls.STATIC_BLACKLIST.add(symbol)

    @classmethod
    def remove_from_blacklist(cls, symbol: str) -> None:
        """Remove a symbol from the static blacklist."""
        cls.STATIC_BLACKLIST.discard(symbol)

    @classmethod
    def get_blacklist(cls) -> set[str]:
        """Get the full blacklist (static + dynamic)."""
        return cls.STATIC_BLACKLIST.copy()

    @staticmethod
    def _check_blacklist(symbol: str, name: str = "", quote_data: dict | None = None) -> list[str]:
        """Auto-detect and blacklist high-risk stocks.

        Checks:
          - ST / *ST prefix in name
          - Static blacklist
          - Daily volume < 50M RMB (low liquidity)
          - Continuous limit-down (consecutive -10%)
          - Delisting warning signals
        """
        violations = []

        # Static blacklist
        if symbol in L4RiskOfficer.STATIC_BLACKLIST:
            violations.append(f"黑名单: {symbol} 在静态黑名单中")
            return violations

        # ST / *ST check
        if name and ("ST" in name.upper() or "*ST" in name.upper()):
            violations.append(f"黑名单: {name} 为ST/*ST股票")
            return violations

        if quote_data:
            # Low liquidity
            volume = quote_data.get("volume", 0) or 0
            price = quote_data.get("price", 0) or 0
            turnover = volume * price  # rough turnover in RMB
            if turnover > 0 and turnover < 50_000_000:  # < 50M daily
                violations.append(f"低流动性: 日成交额 {turnover/1e4:.0f}万 < 5000万")

            # Limit-down streak
            limit_down_streak = quote_data.get("limit_down_streak", 0) or 0
            if limit_down_streak >= 2:
                violations.append(f"连续跌停: {limit_down_streak}天")

            # Delisting risk markers
            if quote_data.get("is_delisting_risk"):
                violations.append("退市风险警示")
            if quote_data.get("audit_opinion") == "non_standard":
                violations.append("审计意见非标")

        return violations
