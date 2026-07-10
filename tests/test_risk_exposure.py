# -*- coding: utf-8 -*-
"""风控引擎三元聚合 + 敞口规则 + 隔离观察 测试。"""

from __future__ import annotations

import pytest
from decimal import Decimal

from src.routing.risk_control import (
    RiskControlEngine,
    RiskCheck,
    RiskVerdict,
    _RuleResult,
)
from src.routing.positioning import TradeSignal
from src.routing.risk_state import RiskState
from src.utils.decimal_utils import D


# ══════════════════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════════════════

def _make_signal(
    symbol: str = "600519",
    action: str = "OPEN",
    target_weight: float = 0.15,
    name: str = "贵州茅台",
    **kwargs,
) -> TradeSignal:
    return TradeSignal(
        symbol=symbol,
        action=action,
        target_weight=target_weight,
        name=name,
        **kwargs,
    )


def _make_engine(equity: float = 1_000_000.0) -> RiskControlEngine:
    return RiskControlEngine(state=RiskState.initial(equity))


# ══════════════════════════════════════════════════════════════════════
# 三元聚合 _aggregate()
# ══════════════════════════════════════════════════════════════════════

class TestTernaryAggregation:
    """REJECT > RESIZE > APPROVE 优先级。"""

    def test_all_approve_passes(self):
        engine = _make_engine()
        rules = [
            _RuleResult(RiskVerdict.APPROVE, []),
            _RuleResult(RiskVerdict.APPROVE, []),
        ]
        result = engine._aggregate(rules, D("0.15"), _make_signal())
        assert result.passed is True
        assert result.adjusted_weight == 0.15

    def test_single_reject_fails(self):
        engine = _make_engine()
        rules = [
            _RuleResult(RiskVerdict.APPROVE, []),
            _RuleResult(RiskVerdict.REJECT, ["黑天鹅"]),
            _RuleResult(RiskVerdict.APPROVE, []),
        ]
        result = engine._aggregate(rules, D("0.15"), _make_signal())
        assert result.passed is False
        assert result.adjusted_weight == 0.0

    def test_reject_beats_resize(self):
        engine = _make_engine()
        rules = [
            _RuleResult(RiskVerdict.RESIZE, ["单票超限"], 0.10),
            _RuleResult(RiskVerdict.REJECT, ["熔断"]),
        ]
        result = engine._aggregate(rules, D("0.15"), _make_signal())
        assert result.passed is False
        assert result.adjusted_weight == 0.0

    def test_multiple_resize_takes_most_conservative(self):
        engine = _make_engine()
        rules = [
            _RuleResult(RiskVerdict.RESIZE, ["单票超限"], 0.10),
            _RuleResult(RiskVerdict.RESIZE, ["行业超限"], 0.05),
            _RuleResult(RiskVerdict.RESIZE, ["总敞口超限"], 0.08),
        ]
        result = engine._aggregate(rules, D("0.20"), _make_signal())
        assert result.passed is True
        assert result.adjusted_weight == pytest.approx(0.05)

    def test_reduce_actions_skip_risk_rules(self):
        """减仓操作应绕过熔断和回撤检查。"""
        engine = _make_engine()
        # 制造熔断状态
        engine._state = engine._state.observe_equity(850_000).trip("test")  # -15%
        signal = _make_signal(action="REDUCE", target_weight=0.05)
        portfolio = {}
        result = engine.check(signal, portfolio)
        # 减仓应放行
        assert result.passed is True
        assert result.adjusted_weight > 0.0


# ══════════════════════════════════════════════════════════════════════
# 敞口规则
# ══════════════════════════════════════════════════════════════════════

class TestExposureRules:

    def test_gross_exposure_resize(self):
        engine = _make_engine()
        signal = _make_signal(target_weight=0.15)
        portfolio = {"current_gross_exposure": 0.90}
        limits = {"max_gross_exposure_pct": 1.0}
        result = engine.check(signal, portfolio, position_limits=limits)
        # 0.90 + 0.15 = 1.05 > 1.0 → 应缩减到 0.10
        assert result.adjusted_weight == pytest.approx(0.10)

    def test_gross_exposure_approve_when_within_limit(self):
        engine = _make_engine()
        signal = _make_signal(target_weight=0.05)
        portfolio = {"current_gross_exposure": 0.80}
        limits = {"max_gross_exposure_pct": 1.0}
        result = engine.check(signal, portfolio, position_limits=limits)
        assert result.passed is True
        assert result.adjusted_weight > 0.0

    def test_gross_exposure_not_enforced_when_not_configured(self):
        engine = _make_engine()
        signal = _make_signal(target_weight=0.50)
        result = engine.check(signal, {})
        # 无敞口限制 → 至少不被敞口规则拦截
        assert result.passed is True

    def test_net_exposure_reducing_direction_always_approved(self):
        """净敞口变小的单永远放行 — RiskGuard 原则。"""
        engine = _make_engine()
        # 净多头 0.60，减仓 → 净敞口变小
        signal = _make_signal(action="REDUCE", target_weight=0.10)
        portfolio = {"current_net_exposure": 0.60}
        limits = {"max_net_exposure_pct": 0.50}
        result = engine.check(signal, portfolio, position_limits=limits)
        assert result.passed is True

    def test_net_exposure_not_enforced_when_not_configured(self):
        engine = _make_engine()
        signal = _make_signal(target_weight=0.30)
        portfolio = {"current_net_exposure": 0.80}
        # 无 net 限制 → 放行
        result = engine.check(signal, portfolio)
        assert result.passed is True


# ══════════════════════════════════════════════════════════════════════
# 隔离观察
# ══════════════════════════════════════════════════════════════════════

class TestQuarantine:

    def test_new_symbol_reduced_in_quarantine(self):
        engine = _make_engine()
        signal = _make_signal(symbol="000001", target_weight=0.15)
        limits = {"quarantine_days": 90, "quarantine_position_pct": 0.01}
        result = engine.check(signal, {}, position_limits=limits)
        # 新标的应被缩减到 1%
        assert result.adjusted_weight == pytest.approx(0.01)
        assert any("隔离期" in v for v in result.violations)

    def test_no_quarantine_when_not_configured(self):
        engine = _make_engine()
        signal = _make_signal(symbol="000001", target_weight=0.15)
        result = engine.check(signal, {})
        # 无隔离配置 → 正常放行
        assert result.passed is True
        assert result.adjusted_weight > 0.0

    def test_quarantine_auto_registers_strategy(self):
        engine = _make_engine()
        signal = _make_signal(symbol="000001", target_weight=0.15)
        limits = {"quarantine_days": 90}
        engine.check(signal, {}, position_limits=limits)
        # 策略应已被自动登记
        age = engine.state.strategy_age_days("000001")
        assert age is not None
        assert age >= 0.0

    def test_quarantine_resize_not_reject(self):
        """隔离是 RESIZE 不是 REJECT — 仍可开仓只是规模更小。"""
        engine = _make_engine()
        signal = _make_signal(symbol="000001", target_weight=0.15)
        limits = {"quarantine_days": 90, "quarantine_position_pct": 0.01}
        result = engine.check(signal, {}, position_limits=limits)
        # passed 应为 True（RESIZE 不等于 REJECT）
        assert result.passed is True
        assert result.adjusted_weight > 0.0


# ══════════════════════════════════════════════════════════════════════
# 回归：原有规则不变
# ══════════════════════════════════════════════════════════════════════

class TestRegression:

    def test_single_stock_cap_resize(self):
        engine = _make_engine()
        signal = _make_signal(target_weight=0.30)  # > 20%
        result = engine.check(signal, {})
        assert result.adjusted_weight == pytest.approx(0.20)

    def test_black_swan_reject(self):
        engine = _make_engine()
        signal = _make_signal(action="OPEN", target_weight=0.10)
        market = {"hs300_change_pct": -0.06}  # -6% < -5%
        result = engine.check(signal, {}, market)
        assert result.passed is False
        assert any("黑天鹅" in v for v in result.violations)

    def test_drawdown_breaker_reject(self):
        engine = _make_engine()
        # 制造 15% 回撤
        engine._state = engine._state.observe_equity(850_000).trip("drawdown")
        signal = _make_signal(action="OPEN", target_weight=0.15)
        result = engine.check(signal, {})
        assert result.passed is False
        assert any("熔断" in v for v in result.violations)

    def test_blacklist_st_stock_reject(self):
        engine = _make_engine()
        signal = _make_signal(symbol="000001", name="*ST测试")
        result = engine.check(signal, {})
        assert result.passed is False
        assert any("黑名单" in v for v in result.violations)

    def test_sector_cap_resize(self):
        engine = _make_engine()
        signal = _make_signal(target_weight=0.20)
        portfolio = {"sector_pct": 0.30}  # 0.30 + 0.20 = 0.50 > 0.40
        result = engine.check(signal, portfolio)
        assert result.adjusted_weight == pytest.approx(0.10)

    def test_breaker_tripped_carried_to_riskcheck(self):
        engine = _make_engine()
        engine._state = engine._state.observe_equity(850_000).trip("drawdown")
        signal = _make_signal(action="OPEN")
        result = engine.check(signal, {})
        assert result.breaker_tripped is True
        assert result.drawdown > 0.10  # ~15% drawdown

    def test_normal_trade_passes_all_rules(self):
        engine = _make_engine()
        signal = _make_signal(symbol="600519", target_weight=0.10)
        result = engine.check(signal, {})
        assert result.passed is True
        assert result.adjusted_weight == pytest.approx(0.10)
