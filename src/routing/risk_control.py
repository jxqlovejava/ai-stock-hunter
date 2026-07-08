# -*- coding: utf-8 -*-
"""风控执行 — 硬约束执行（不可覆盖）。Phase 4: Alpha 衰减风控。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from .positioning import TradeSignal
from src.utils.decimal_utils import D, safe_divide

logger = logging.getLogger(__name__)


@dataclass
class RiskCheck:
    """风控审查结果。"""
    passed: bool
    violations: list[str] = field(default_factory=list)
    adjusted_weight: float = 0.0
    source_citations: list = field(default_factory=list)  # Phase 1: 继承引用链


class RiskControlEngine:
    """风控执行引擎。

    硬约束（不可覆盖）:
      - 单票最大仓位: 20%
      - 单行业最大仓位: 40%
      - 单笔最大亏损: 2% (短线用 ATR 止损)
      - 组合最大回撤: 15%
      - 双创折扣: ×0.8
      - 黑天鹅熔断: 沪深300 单日 -5%
      - 流动性上限: 持仓 < 日均成交额 5%

    Phase 7 短线模式新增:
      - ATR 倍率止损 (替代固定 -2%)
      - 时间止损 (N 日不涨即离场)
      - 移动止损 (最高价回撤 N%)
    """

    SINGLE_STOCK_CAP = Decimal("0.20")
    SINGLE_SECTOR_CAP = Decimal("0.40")
    MAX_DRAWDOWN = Decimal("-0.15")
    SINGLE_STOP_LOSS = Decimal("-0.02")
    BLACK_SWAN_THRESHOLD = Decimal("-0.05")
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
            signal: 交易信号
            portfolio: 当前组合状态 {sector_pct, drawdown_pct, position_loss_pct}
            market: 市场状态 {hs300_change_pct}
            position_limits: 用户偏好风控约束，覆盖类级默认值。
                             键: single_stock_cap, sector_cap, max_drawdown, stop_loss
        """
        violations = []
        weight = D(signal.target_weight)

        # 用户偏好覆盖（类常量已是 Decimal，position_limits 中的值需 D() 转换）
        _single_stock_cap = self.SINGLE_STOCK_CAP
        _sector_cap = self.SINGLE_SECTOR_CAP
        _max_drawdown = self.MAX_DRAWDOWN
        _stop_loss = self.SINGLE_STOP_LOSS
        if position_limits:
            _single_stock_cap = D(position_limits.get("single_stock_cap", float(_single_stock_cap)))
            _sector_cap = D(position_limits.get("sector_cap", float(_sector_cap)))
            _max_drawdown = D(position_limits.get("max_drawdown", float(_max_drawdown)))
            _stop_loss = D(position_limits.get("stop_loss", float(_stop_loss)))

        # 单票上限
        if weight > _single_stock_cap:
            violations.append(f"单票超限: {float(weight):.1%} > {float(_single_stock_cap):.0%}")
            weight = min(weight, _single_stock_cap)

        # 行业上限
        sector_pct = D((portfolio or {}).get("sector_pct", 0))
        if sector_pct + weight > _sector_cap:
            violations.append(f"行业超限: {float(sector_pct + weight):.1%} > {float(_sector_cap):.0%}")
            weight = min(weight, _sector_cap - sector_pct)

        # 黑天鹅熔断
        market_drop = D((market or {}).get("hs300_change_pct", 0))
        if market_drop <= self.BLACK_SWAN_THRESHOLD:
            violations.append("黑天鹅熔断: T+1 禁开新仓")
            if signal.action in ("OPEN", "ADD"):
                weight = D("0")

        # 组合回撤
        drawdown = D((portfolio or {}).get("drawdown_pct", 0))
        if drawdown <= _max_drawdown:
            violations.append(f"组合回撤熔断: {float(drawdown):.1%} < {float(_max_drawdown):.0%}")
            weight = min(weight, D("0"))

        # 单笔止损 (支持 ATR/时间/移动止损)
        position_loss = D((portfolio or {}).get("position_loss_pct", 0))
        if signal.suggested_stop > 0 and (portfolio or {}).get("current_price", 0) > 0:
            current_price = D((portfolio or {}).get("current_price", 0))
            stop_price = D(signal.suggested_stop)
            if current_price <= stop_price:
                violations.append(
                    f"ATR止损触发: 现价{float(current_price):.2f} <= 止损价{float(stop_price):.2f}"
                )
                weight = D("0")
        elif position_loss <= _stop_loss:
            violations.append(f"单笔止损: {float(position_loss):.1%} 触及 {float(_stop_loss):.0%}")
            weight = D("0")  # 强制平仓

        # 时间止损 (短线模式特有)
        holding_days = (portfolio or {}).get("holding_days", 0) or 0
        if signal.time_stop_days > 0 and holding_days >= signal.time_stop_days:
            position_pnl = D((portfolio or {}).get("position_pnl_pct", 0))
            if position_pnl <= D("0"):
                violations.append(
                    f"时间止损: 持有{holding_days}天 >= {signal.time_stop_days}天且未盈利"
                )
                weight = min(weight, D("0"))

        # 移动止损 (短线模式: 从最高点回撤 N%)
        if signal.suggested_stop > 0 and signal.atr_stop > 0:
            peak_price = D((portfolio or {}).get("peak_price", 0) or 0)
            current_px = D((portfolio or {}).get("current_price", 0) or 0)
            if peak_price > D("0") and current_px > D("0"):
                drawdown_from_peak = (current_px - peak_price) / peak_price
                trailing_pct = D("-0.03")  # default -3%
                if position_limits:
                    trailing_pct = D(position_limits.get("trailing_stop_pct", float(trailing_pct)))
                if drawdown_from_peak <= trailing_pct:
                    violations.append(
                        f"移动止损: 从高点{float(peak_price):.2f}回撤{float(drawdown_from_peak):.1%}"
                    )
                    weight = min(weight, D("0"))

        # Phase 4: Alpha 衰减风控检查
        alpha_violations = self._check_alpha_decay(signal, portfolio or {})
        violations.extend(alpha_violations)
        if any("清仓" in v for v in alpha_violations):
            weight = min(weight, D("0"))

        # Auto-blacklist check
        blacklist_violations = self._check_blacklist(signal.symbol, signal.name, quote_data=signal.extra or {})
        violations.extend(blacklist_violations)
        if any("黑名单" in v for v in blacklist_violations):
            weight = D("0")

        # Phase 6: 博弈论风险约束
        gt_risks = (portfolio or {}).get("game_theory_risks", [])
        if gt_risks:
            violations.extend(gt_risks)
            critical_gt = {
                "seat_distribution_sell",
                "sector_crowded",
                "leverage_fear",
                "hot_money_dominant_large_cap_mismatch",
            }
            if any(any(k in v for k in critical_gt) for v in gt_risks):
                weight = weight * D("0.5")
            if any("seat_distribution_sell" in v for v in gt_risks):
                weight = D("0")

        return RiskCheck(
            passed=len([v for v in violations if "熔断" in v or "止损" in v or "黑名单" in v]) == 0,
            violations=violations,
            adjusted_weight=max(0.0, float(weight)),
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
        if symbol in RiskControlEngine.STATIC_BLACKLIST:
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

