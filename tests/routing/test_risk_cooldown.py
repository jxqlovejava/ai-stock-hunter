# -*- coding: utf-8 -*-
"""P0-3 风控对齐 + 单笔风险预算仓位。

覆盖:
  ① 单日黑天鹅熔断 5%→6%（-6% REJECT，-5% 不再触发）
  ② 连续 3 次止损 → 冷却生效，暂停自动开仓
  ③ risk-budget sizing: (equity×risk_budget_pct)/(entry−stop) 与乘数链取 min
  ④ ctx 注入 consecutive_stops（orchestrator → 军规 r017）
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.routing.positioning import PositioningEngine, TradeSignal
from src.routing.risk_control import RiskControlEngine
from src.routing.risk_state import RiskState
from src.routing.verdict import Verdict


def _make_signal(
    action: str = "OPEN",
    weight: float = 0.15,
    symbol: str = "600519",
    name: str = "贵州茅台",
    **kw,
) -> TradeSignal:
    return TradeSignal(
        symbol=symbol,
        action=action,
        target_weight=weight,
        name=name,
        **kw,
    )


def _engine(equity: float = 1_000_000.0) -> RiskControlEngine:
    return RiskControlEngine(state=RiskState.initial(equity))


def _verdict(score: int = 88) -> Verdict:
    return Verdict(symbol="600519", score=score, confidence=0.8, recommendation="BUY")


class _Timing:
    """最小 timing_result 桩。"""

    def __init__(self, suggested_stop: float):
        self.best_entry = None
        self.exit_signals = []
        self.suggested_stop = suggested_stop
        self.time_stop_days = 30
        self.atr_stop = suggested_stop
        self.target_1 = 0.0
        self.target_2 = 0.0


# ══════════════════════════════════════════════════════════════════════
# ① 单日黑天鹅熔断 5%→6%
# ══════════════════════════════════════════════════════════════════════

class TestBlackSwanThreshold6:

    def test_six_pct_drop_rejects_open(self):
        eng = _engine()
        result = eng.check(_make_signal(), {}, market={"hs300_change_pct": -0.06})
        assert result.passed is False
        assert result.adjusted_weight == 0.0
        assert any("黑天鹅" in v for v in result.violations)

    def test_five_pct_drop_no_longer_rejects(self):
        """P0-3 熔断 5%→6%: 5% 跌幅不再触发黑天鹅 REJECT。"""
        eng = _engine()
        result = eng.check(_make_signal(), {}, market={"hs300_change_pct": -0.05})
        assert result.passed is True
        assert not any("黑天鹅" in v for v in result.violations)

    def test_add_action_also_rejected(self):
        eng = _engine()
        result = eng.check(_make_signal(action="ADD"), {}, market={"hs300_change_pct": -0.08})
        assert result.passed is False

    def test_reduce_never_blocked_by_black_swan(self):
        eng = _engine()
        result = eng.check(
            _make_signal(action="REDUCE", weight=0.05),
            {},
            market={"hs300_change_pct": -0.08},
        )
        assert result.passed is True


# ══════════════════════════════════════════════════════════════════════
# ② 连续止损冷却
# ══════════════════════════════════════════════════════════════════════

class TestConsecutiveStopCooldown:

    def test_three_stops_trigger_cooldown_and_reject_open(self):
        eng = _engine()
        for _ in range(3):
            eng.record_stop_loss()
        assert eng.consecutive_stops == 3
        assert eng.in_cooldown is True
        result = eng.check(_make_signal(action="OPEN"), {})
        assert result.passed is False
        assert any("冷却" in v for v in result.violations)

    def test_below_threshold_no_reject(self):
        eng = _engine()
        for _ in range(2):
            eng.record_stop_loss()
        assert eng.consecutive_stops == 2
        result = eng.check(_make_signal(action="OPEN"), {})
        assert result.passed is True

    def test_win_resets_counter_and_cooldown(self):
        eng = _engine()
        for _ in range(3):
            eng.record_stop_loss()
        assert eng.in_cooldown is True
        eng.record_win()
        assert eng.consecutive_stops == 0
        assert eng.in_cooldown is False
        result = eng.check(_make_signal(action="OPEN"), {})
        assert result.passed is True

    def test_reduce_allowed_during_cooldown(self):
        eng = _engine()
        for _ in range(3):
            eng.record_stop_loss()
        result = eng.check(_make_signal(action="REDUCE", weight=0.05), {})
        assert result.passed is True

    def test_cooldown_expires_after_days_and_resets(self):
        now = datetime.now(timezone.utc)
        eng = _engine()
        for _ in range(3):
            eng.record_stop_loss(now=now)
        assert eng.in_cooldown is True
        later = now + timedelta(days=4)
        assert eng._state.in_cooldown(now=later) is False
        assert eng._state.advance_time(now=later).consecutive_stops == 0

    def test_threshold_configurable_via_position_limits(self):
        eng = _engine()
        for _ in range(2):
            eng.record_stop_loss()
        result = eng.check(
            _make_signal(action="OPEN"),
            {},
            position_limits={"consecutive_stop_threshold": 2},
        )
        assert result.passed is False
        assert any("冷却" in v for v in result.violations)


# ══════════════════════════════════════════════════════════════════════
# ③ risk-budget sizing（单笔风险预算反推仓位）
# ══════════════════════════════════════════════════════════════════════

class TestRiskBudgetSizing:

    def test_cap_leq_multiplier_chain(self):
        """乘数链 0.608，风险预算 cap=0.40 → 取 min 得 0.40。"""
        pe = PositioningEngine(kelly_sizer=None)
        sig = pe.generate_signal(
            _verdict(),
            macro_cap=0.8,
            extra={"price": 100.0},
            timing_result=_Timing(suggested_stop=95.0),
            portfolio_value=1_000_000,
        )
        assert sig.target_weight == pytest.approx(0.40)

    def test_cap_not_tighter_when_stop_far(self):
        """止损较远 → cap 较大，乘数链结果不变（min 不收紧）。"""
        pe = PositioningEngine(kelly_sizer=None)
        sig = pe.generate_signal(
            _verdict(),
            macro_cap=0.8,
            extra={"price": 100.0},
            timing_result=_Timing(suggested_stop=70.0),  # cap = 0.02*100/30 = 0.0667
            portfolio_value=1_000_000,
        )
        assert sig.target_weight == pytest.approx(0.0667)

    def test_fallback_without_stop(self):
        """suggested_stop 缺失 → 回退乘数链，不报错。"""
        pe = PositioningEngine(kelly_sizer=None)
        sig = pe.generate_signal(
            _verdict(),
            macro_cap=0.8,
            extra={"price": 100.0},
            timing_result=_Timing(suggested_stop=0.0),
        )
        assert sig.target_weight == pytest.approx(0.608)

    def test_fallback_stop_gte_entry(self):
        """止损 ≥ 入场 → 风险模型失效，回退乘数链。"""
        pe = PositioningEngine(kelly_sizer=None)
        sig = pe.generate_signal(
            _verdict(),
            macro_cap=0.8,
            extra={"price": 100.0},
            timing_result=_Timing(suggested_stop=100.0),
            portfolio_value=1_000_000,
        )
        assert sig.target_weight == pytest.approx(0.608)

    def test_risk_budget_pct_configurable(self):
        """risk_budget_pct=0.01 → cap = 0.01*100/5 = 0.20。"""
        pe = PositioningEngine(kelly_sizer=None)
        sig = pe.generate_signal(
            _verdict(),
            macro_cap=0.8,
            extra={"price": 100.0},
            timing_result=_Timing(suggested_stop=95.0),
            position_limits={"risk_budget_pct": 0.01},
            portfolio_value=1_000_000,
        )
        assert sig.target_weight == pytest.approx(0.20)

    def test_suggested_stop_param_caps_weight(self):
        """全量路径直接传 suggested_stop（无 timing_result）→ risk-budget cap 生效。

        乘数链 0.608，risk_budget_pct=0.02, entry=100, stop=95
        → cap = 0.02*100/5 = 0.40 → 取 min 得 0.40。
        """
        pe = PositioningEngine(kelly_sizer=None)
        sig = pe.generate_signal(
            _verdict(),
            macro_cap=0.8,
            extra={"price": 100.0},
            suggested_stop=95.0,
            portfolio_value=1_000_000,
        )
        assert sig.target_weight == pytest.approx(0.40)

    def test_suggested_stop_param_fallback_without_stop(self):
        """suggested_stop 缺失 → 回退乘数链，不报错。"""
        pe = PositioningEngine(kelly_sizer=None)
        sig = pe.generate_signal(
            _verdict(),
            macro_cap=0.8,
            extra={"price": 100.0},
        )
        assert sig.target_weight == pytest.approx(0.608)

    def test_suggested_stop_param_stop_gte_entry_fallback(self):
        """suggested_stop ≥ 入场 → 风险模型失效，回退乘数链。"""
        pe = PositioningEngine(kelly_sizer=None)
        sig = pe.generate_signal(
            _verdict(),
            macro_cap=0.8,
            extra={"price": 100.0},
            suggested_stop=100.0,
        )
        assert sig.target_weight == pytest.approx(0.608)


# ══════════════════════════════════════════════════════════════════════
# ③b 全量路径 suggested_stop 推导（orchestrator → risk-budget sizing）
# ══════════════════════════════════════════════════════════════════════

class TestEntryStopDerivation:
    """Orchestrator._entry_stop_for_sizing：T+0 止损 / 固定止损百分比推导。"""

    def _helper(self, t0, quote, quote_dict, position_limits):
        from src.routing.orchestrator import Orchestrator
        return Orchestrator._entry_stop_for_sizing(t0, quote, quote_dict, position_limits)

    def test_t0_stop_loss_used(self):
        """T+0 引擎止损优先。"""
        from types import SimpleNamespace
        stop, entry = self._helper(
            {"stop_loss": 9.5},
            SimpleNamespace(price=10.0),
            {},
            None,
        )
        assert stop == pytest.approx(9.5)
        assert entry == pytest.approx(10.0)

    def test_fixed_pct_fallback_without_t0(self):
        """无 T+0 → 固定止损百分比回退（-5% → stop=9.5）。"""
        stop, entry = self._helper(
            None,
            None,
            {"price": 10.0},
            {"stop_loss": -0.05},
        )
        assert stop == pytest.approx(9.5)
        assert entry == pytest.approx(10.0)

    def test_default_stop_loss_pct(self):
        """position_limits 无 stop_loss → 默认 -2% → stop=9.8。"""
        stop, entry = self._helper(
            None,
            None,
            {"close": 10.0},
            None,
        )
        assert stop == pytest.approx(9.8)
        assert entry == pytest.approx(10.0)

    def test_no_price_no_stop_returns_zero(self):
        """取不到入场价/止损 → 返回 (0.0, 0.0)，generate_signal 回退不报错。"""
        stop, entry = self._helper(None, None, {}, None)
        assert stop == 0.0
        assert entry == 0.0


# ══════════════════════════════════════════════════════════════════════
# ④ ctx 注入 consecutive_stops（orchestrator → 军规 r017）
# ══════════════════════════════════════════════════════════════════════

class TestCtxConsecutiveStops:

    def test_inject_zero_when_clean(self):
        from src.routing.orchestrator import Orchestrator
        orch = Orchestrator()
        ctx = {"stock_name": "测试"}
        orch._inject_risk_state_ctx(ctx)
        assert ctx["consecutive_stops"] == 0

    def test_inject_count_after_stops(self):
        from src.routing.orchestrator import Orchestrator
        orch = Orchestrator()
        for _ in range(3):
            orch.risk_ctrl.record_stop_loss()
        ctx = {"stock_name": "测试"}
        orch._inject_risk_state_ctx(ctx)
        assert ctx["consecutive_stops"] == 3

    def test_r017_blocks_at_three_consecutive_stops(self):
        """军规 r017: ctx.consecutive_stops >= 3 → BLOCK（对应冷却语义）。"""
        from src.doctrine.checker import DoctrineChecker
        result = DoctrineChecker().check("600519", {"consecutive_stops": 3})
        assert result.passed is False
        assert any(r.id == "r017" for r in result.blocked_by)

    def test_r017_not_triggered_below_three(self):
        from src.doctrine.checker import DoctrineChecker
        result = DoctrineChecker().check("600519", {"consecutive_stops": 2})
        assert not any(r.id == "r017" for r in result.blocked_by)
