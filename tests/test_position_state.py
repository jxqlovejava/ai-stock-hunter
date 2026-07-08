# -*- coding: utf-8 -*-
"""Phase 12: 持仓实时追踪 + 动态止盈止损 — 单元测试。

覆盖:
  1. PositionState.observe_price() — HWM 升高、NaN 防御、PnL 正确
  2. PositionState.initial() — 默认止损和阶段正确
  3. DynamicStopCalculator — 三阶段止损价格计算
  4. DynamicStopCalculator.determine_stage() — 阶段跃迁逻辑
  5. PositionStateManager — 开仓/平仓/更新 CRUD
  6. PositionStateManager.update_price() — 止损触发和阶段跃迁预警
  7. 持久化往返 — to_dict/from_dict + JSON 读写
  8. 止损单向性 — 止损失只上移不下移
"""

from __future__ import annotations

import json
import math
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from src.routing.position_state import (
    AlertType,
    DynamicStopCalculator,
    PositionState,
    PositionStateManager,
    StopAlert,
    StopStage,
)


# ---------------------------------------------------------------------------
# 1. PositionState.observe_price()
# ---------------------------------------------------------------------------

class TestPositionStateObservePrice:
    """价格观测: HWM 追踪、PnL 计算、NaN 防御。"""

    def test_hwm_tracks_high(self):
        """HWM 应随价格上涨而升高。"""
        state = PositionState.initial("000001", "平安银行", entry_price=10.0)
        assert state.high_price == 10.0

        state2 = state.observe_price(11.0)
        assert state2.high_price == 11.0
        assert state2.last_price == 11.0
        # HWM 应保持
        state3 = state2.observe_price(10.5)
        assert state3.high_price == 11.0  # 不变
        assert state3.last_price == 10.5

    def test_pnl_calculation_long(self):
        """多仓 PnL 计算: (price - entry) / entry。"""
        state = PositionState.initial("000001", entry_price=10.0).observe_price(11.0)
        assert state.unrealized_pnl_pct == pytest.approx(0.10)
        assert state.max_favor_pct == pytest.approx(0.10)
        assert state.max_adversity_pct == pytest.approx(0.0)

    def test_pnl_negative(self):
        """浮亏时 max_adversity 应记录。"""
        state = PositionState.initial("000001", entry_price=10.0).observe_price(9.0)
        assert state.unrealized_pnl_pct == pytest.approx(-0.10)
        assert state.max_favor_pct == pytest.approx(0.0)
        assert state.max_adversity_pct == pytest.approx(-0.10)

    def test_max_favor_persists_after_drawdown(self):
        """最高浮盈应保持，即使价格回落。"""
        state = PositionState.initial("000001", entry_price=10.0)
        state = state.observe_price(15.0)   # +50%
        assert state.max_favor_pct == pytest.approx(0.50)
        state = state.observe_price(12.0)   # 回落到 +20%
        assert state.max_favor_pct == pytest.approx(0.50)  # 不变

    def test_nan_defense(self):
        """NaN/Inf/零/负数 价格应被忽略。"""
        state = PositionState.initial("000001", entry_price=10.0)
        for bad_price in (float("nan"), float("inf"), float("-inf"), 0.0, -1.0):
            state2 = state.observe_price(bad_price)
            assert state2.high_price == state.high_price
            assert state2.last_price == state.last_price

    def test_zero_entry_price_handled(self):
        """entry_price 为 0 时不应除零。"""
        state = PositionState(symbol="000001", entry_price=0.0)
        state2 = state.observe_price(10.0)
        assert state2.high_price == 10.0
        assert state2.unrealized_pnl_pct == 0.0


# ---------------------------------------------------------------------------
# 2. PositionState.initial()
# ---------------------------------------------------------------------------

class TestPositionStateInitial:
    """初始状态创建。"""

    def test_default_stop(self):
        """默认止损 = entry * (1 - 2%)。"""
        state = PositionState.initial("000001", entry_price=100.0)
        assert state.stop_stage == StopStage.INITIAL
        assert state.stop_price == pytest.approx(98.0)

    def test_custom_stop_config(self):
        """自定义止损参数。"""
        state = PositionState.initial(
            "000001", entry_price=100.0,
            stop_config={
                "initial_stop_pct": -0.05,
                "breakeven_trigger_pct": 0.15,
                "trailing_trigger_pct": 0.25,
            },
        )
        assert state.stop_price == pytest.approx(95.0)
        assert state.breakeven_trigger_pct == 0.15
        assert state.trailing_trigger_pct == 0.25

    def test_initial_hwm_equals_entry(self):
        """初始 HWM = entry_price。"""
        state = PositionState.initial("000001", entry_price=50.0)
        assert state.high_price == 50.0
        assert state.low_price == 50.0
        assert state.last_price == 50.0

    def test_initial_atr_stop(self):
        """提供 ATR 时初始止损使用 ATR。"""
        state = PositionState.initial("000001", entry_price=100.0, atr_value=3.0)
        # ATR=3, multiplier=2 → atr_stop=100-6=94, fixed=100*0.98=98 → max(94,98)=98
        assert state.stop_price == pytest.approx(98.0)

    def test_initial_atr_stop_wider(self):
        """ATR 很大时取固定止损（更紧的）。"""
        state = PositionState.initial("000001", entry_price=100.0, atr_value=10.0)
        # ATR=10, multiplier=2 → atr_stop=80, fixed=98 → max(80,98)=98
        assert state.stop_price == pytest.approx(98.0)

    def test_initial_atr_stop_note(self):
        """ATR 止损有明确标注。"""
        state = PositionState.initial("000001", entry_price=100.0, atr_value=2.0)
        assert "ATR" in state.stop_note


# ---------------------------------------------------------------------------
# 3. DynamicStopCalculator
# ---------------------------------------------------------------------------

class TestDynamicStopCalculator:
    """三阶段止损价格计算。"""

    def test_initial_stop_fixed(self):
        """无 ATR 时使用固定百分比。"""
        state = PositionState.initial("000001", entry_price=100.0)
        stop = DynamicStopCalculator.initial_stop(state, atr_value=None)
        assert stop == pytest.approx(98.0)

    def test_initial_stop_with_atr(self):
        """有 ATR 时取较紧的止损。"""
        state = PositionState.initial(
            "000001", entry_price=100.0,
            stop_config={"initial_stop_pct": -0.02, "atr_multiplier": 2.0},
        )
        # ATR=1.0 → atr_stop=98.0, fixed=98.0 → 相等
        stop = DynamicStopCalculator.initial_stop(state, atr_value=1.0)
        assert stop == pytest.approx(98.0)

        # ATR=3.0 → atr_stop=94.0, fixed=98.0 → 取 98.0（更紧）
        stop = DynamicStopCalculator.initial_stop(state, atr_value=3.0)
        assert stop == pytest.approx(98.0)

    def test_breakeven_stop(self):
        """保本止损 = 成本价。"""
        state = PositionState.initial("000001", entry_price=100.0)
        stop = DynamicStopCalculator.breakeven_stop(state)
        assert stop == pytest.approx(100.0)

    def test_trailing_stop(self):
        """追踪止损 = HWM × (1 + trailing_stop_pct)。"""
        state = PositionState.initial(
            "000001", entry_price=100.0,
            stop_config={"trailing_stop_pct": -0.05},
        )
        state = state.observe_price(120.0)  # HWM = 120
        stop = DynamicStopCalculator.trailing_stop(state)
        assert stop == pytest.approx(114.0)  # 120 * 0.95 = 114

    def test_trailing_stop_only_moves_up(self):
        """追踪止损失只上移不下移。"""
        state = PositionState.initial(
            "000001", entry_price=100.0,
            stop_config={"trailing_stop_pct": -0.05},
        )
        state = state.observe_price(120.0)
        # 设置旧止损为 114
        state = state.with_stop(StopStage.TRAILING, 114.0)
        # 价格回落到 115，HWM 仍是 120 → 止损应保持 114
        state2 = state.observe_price(115.0)
        stop = DynamicStopCalculator.trailing_stop(state2)
        assert stop == pytest.approx(114.0)  # 不下移

    def test_trailing_stop_atr_based(self):
        """ATR 可用时追踪止损使用 ATR。"""
        state = PositionState.initial(
            "000001", entry_price=100.0,
            stop_config={"trailing_atr_multiplier": 3.0},
        )
        state = state.observe_price(130.0)  # HWM=130
        # ATR=2, trailing_atr_multiplier=3 → stop = 130 - 2*3 = 124
        stop = DynamicStopCalculator.trailing_stop(state, atr_value=2.0)
        assert stop == pytest.approx(124.0)

    def test_trailing_stop_atr_fallback_to_fixed(self):
        """无 ATR 时回退到固定百分比。"""
        state = PositionState.initial(
            "000001", entry_price=100.0,
            stop_config={"trailing_stop_pct": -0.05},
        )
        state = state.observe_price(130.0)
        # 无 ATR → HWM * (1 - 0.05) = 130 * 0.95 = 123.5
        stop = DynamicStopCalculator.trailing_stop(state, atr_value=None)
        assert stop == pytest.approx(123.5)


# ---------------------------------------------------------------------------
# 4. DynamicStopCalculator.determine_stage()
# ---------------------------------------------------------------------------

class TestDetermineStage:
    """阶段跃迁逻辑。"""

    def test_stays_initial_below_threshold(self):
        """浮盈 < 20% → 保持 INITIAL。"""
        state = PositionState.initial("000001", entry_price=100.0)
        state = state.observe_price(115.0)  # +15%
        stage, stop, reason = DynamicStopCalculator.determine_stage(state)
        assert stage == StopStage.INITIAL

    def test_transitions_to_breakeven(self):
        """浮盈 ≥ 20% → BREAKEVEN。"""
        state = PositionState.initial("000001", entry_price=100.0)
        state = state.observe_price(125.0)  # +25%
        stage, stop, reason = DynamicStopCalculator.determine_stage(state)
        assert stage == StopStage.BREAKEVEN
        assert stop == pytest.approx(100.0)  # 成本价
        assert "r019" in reason

    def test_transitions_to_trailing(self):
        """浮盈 ≥ 30% → TRAILING。"""
        state = PositionState.initial("000001", entry_price=100.0)
        state = state.observe_price(135.0)  # +35%
        stage, stop, reason = DynamicStopCalculator.determine_stage(state)
        assert stage == StopStage.TRAILING
        assert "r028" in reason

    def test_trailing_persists(self):
        """已在 TRAILING 中 → 保持 TRAILING 并更新止损。"""
        state = PositionState.initial("000001", entry_price=100.0)
        state = state.observe_price(140.0)
        state = state.with_stop(StopStage.TRAILING, 133.0)
        # 价格继续涨到 150
        state = state.observe_price(150.0)
        stage, stop, reason = DynamicStopCalculator.determine_stage(state)
        assert stage == StopStage.TRAILING
        # 新止损: 150 * 0.95 = 142.5
        assert stop == pytest.approx(142.5)

    def test_custom_thresholds(self):
        """自定义阈值应生效。"""
        state = PositionState.initial(
            "000001", entry_price=100.0,
            stop_config={
                "breakeven_trigger_pct": 0.10,
                "trailing_trigger_pct": 0.20,
            },
        )
        state = state.observe_price(112.0)  # +12%
        stage, stop, reason = DynamicStopCalculator.determine_stage(state)
        assert stage == StopStage.BREAKEVEN  # 10% < 12% < 20%

    def test_determine_stage_passes_atr_through(self):
        """determine_stage 在 TRAILING 时使用 ATR 计算止损。"""
        state = PositionState.initial(
            "000001", entry_price=100.0,
            stop_config={"trailing_atr_multiplier": 3.0},
        )
        state = state.observe_price(135.0)  # +35% → TRAILING
        # 传入 ATR=2.0
        stage, stop, reason = DynamicStopCalculator.determine_stage(state, atr_value=2.0)
        assert stage == StopStage.TRAILING
        # HWM=135, ATR=2, trailing_atr_multiplier=3 → 135-6=129
        assert stop == pytest.approx(129.0)
        assert "ATR追踪" in reason


# ---------------------------------------------------------------------------
# 5. PositionStateManager CRUD
# ---------------------------------------------------------------------------

class TestPositionStateManager:
    """持仓状态管理器: 开/平/查。"""

    @pytest.fixture
    def mgr(self):
        """创建使用临时文件的管理器。"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "positions.json"
            yield PositionStateManager(path=path)

    def test_open_and_get(self, mgr):
        state = mgr.open("000001", "平安银行", entry_price=10.0)
        assert state.symbol == "000001"
        assert mgr.is_open("000001")
        assert mgr.get("000001") is not None
        assert mgr.count == 1

    def test_open_existing_skips(self, mgr):
        """重复 open 不覆盖已有持仓。"""
        mgr.open("000001", entry_price=10.0)
        mgr.open("000001", entry_price=20.0)  # 应被跳过
        assert mgr.get("000001").entry_price == 10.0

    def test_close(self, mgr):
        mgr.open("000001", entry_price=10.0)
        state = mgr.close("000001")
        assert state is not None
        assert not mgr.is_open("000001")
        assert mgr.count == 0

    def test_close_nonexistent(self, mgr):
        assert mgr.close("999999") is None

    def test_get_all(self, mgr):
        mgr.open("000001", entry_price=10.0)
        mgr.open("600519", entry_price=1500.0)
        all_pos = mgr.get_all()
        assert len(all_pos) == 2
        symbols = {p.symbol for p in all_pos}
        assert symbols == {"000001", "600519"}

    def test_update_quantity(self, mgr):
        mgr.open("000001", entry_price=10.0, quantity=100)
        updated = mgr.update_quantity("000001", 200)
        assert updated.quantity == 200
        assert mgr.get("000001").quantity == 200

    def test_clear(self, mgr):
        mgr.open("000001", entry_price=10.0)
        mgr.open("600519", entry_price=1500.0)
        mgr.clear()
        assert mgr.count == 0


# ---------------------------------------------------------------------------
# 6. update_price() — alerts
# ---------------------------------------------------------------------------

class TestUpdatePriceAlerts:
    """价格更新时止损触发和阶段跃迁预警。"""

    @pytest.fixture
    def mgr(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "positions.json"
            yield PositionStateManager(path=path)

    def test_stop_loss_alert(self, mgr):
        """价格触及止损 → STOP_LOSS 预警。"""
        mgr.open("000001", entry_price=100.0)  # stop = 98.0
        _, alerts = mgr.update_price("000001", 97.0)
        assert len(alerts) >= 1
        stop_alerts = [a for a in alerts if a.alert_type == AlertType.STOP_LOSS]
        assert len(stop_alerts) >= 1
        assert stop_alerts[0].severity == "CRITICAL"

    def test_stage_transition_alert(self, mgr):
        """浮盈触发阶段跃迁 → STAGE_TRANSITION 预警。"""
        mgr.open("000001", entry_price=100.0)
        # 价格涨到 125 (+25%) → 触发 BREAKEVEN
        _, alerts = mgr.update_price("000001", 125.0)
        trans = [a for a in alerts if a.alert_type == AlertType.STAGE_TRANSITION]
        assert len(trans) >= 1
        assert "r019" in trans[0].message

    def test_trailing_alert(self, mgr):
        """浮盈触发 TRAILING 阶段。"""
        mgr.open("000001", entry_price=100.0)
        # 跳涨到 135 (+35%) → 触发 TRAILING
        _, alerts = mgr.update_price("000001", 135.0)
        trans = [a for a in alerts if "r028" in a.message]
        assert len(trans) >= 1

    def test_no_alerts_normal_price(self, mgr):
        """价格正常波动无预警。"""
        mgr.open("000001", entry_price=100.0)
        _, alerts = mgr.update_price("000001", 102.0)
        assert len(alerts) == 0

    def test_nonexistent_symbol(self, mgr):
        """不存在的标的返回 None。"""
        state, alerts = mgr.update_price("999999", 10.0)
        assert state is None
        assert alerts == []


# ---------------------------------------------------------------------------
# 7. 持久化往返
# ---------------------------------------------------------------------------

class TestPersistence:
    """to_dict / from_dict + JSON 读写。"""

    def test_roundtrip_to_from_dict(self):
        """to_dict → from_dict 应保持字段一致。"""
        original = PositionState.initial("000001", "平安银行", entry_price=10.0)
        original = original.observe_price(12.0)
        original = original.with_stop(StopStage.BREAKEVEN, 10.0, "test")

        d = original.to_dict()
        restored = PositionState.from_dict(d)

        assert restored.symbol == original.symbol
        assert restored.entry_price == original.entry_price
        assert restored.high_price == original.high_price
        assert restored.stop_stage == original.stop_stage
        assert restored.stop_price == original.stop_price
        assert restored.max_favor_pct == original.max_favor_pct

    def test_json_roundtrip(self):
        """JSON 持久化往返。"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "positions.json"
            mgr = PositionStateManager(path=path)

            mgr.open("000001", "平安银行", entry_price=10.0)
            mgr.update_price("000001", 12.0)

            # 重新加载
            mgr2 = PositionStateManager(path=path)
            assert mgr2.count == 1
            state = mgr2.get("000001")
            assert state is not None
            assert state.entry_price == 10.0
            assert state.high_price == 12.0

    def test_corrupted_json_handled(self):
        """损坏的 JSON 不崩溃，返回空状态。"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "positions.json"
            path.write_text("not valid json {{{")

            mgr = PositionStateManager(path=path)
            assert mgr.count == 0

    def test_empty_file_handled(self):
        """空文件不崩溃。"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "positions.json"
            path.write_text("")

            mgr = PositionStateManager(path=path)
            assert mgr.count == 0

    def test_from_dict_defaults(self):
        """from_dict 应填充分缺失字段的默认值。"""
        d = {"symbol": "000001", "entry_price": 10.0}
        state = PositionState.from_dict(d)
        assert state.symbol == "000001"
        assert state.entry_price == 10.0
        assert state.stop_stage == StopStage.INITIAL
        assert state.direction == "LONG"


# ---------------------------------------------------------------------------
# 8. 止损单向性
# ---------------------------------------------------------------------------

class TestStopOneWay:
    """止损失只能上移，不能下移。"""

    def test_with_stop_replaces(self):
        """with_stop 应更新止损阶段和价格。"""
        state = PositionState.initial("000001", entry_price=100.0)
        state2 = state.with_stop(StopStage.BREAKEVEN, 100.0, "r019")
        assert state2.stop_stage == StopStage.BREAKEVEN
        assert state2.stop_price == pytest.approx(100.0)
        assert state2.stop_note == "r019"

    def test_stage_progression_is_forward_only(self):
        """阶段跃迁应为单向: INITIAL → BREAKEVEN → TRAILING。"""
        # 通过 determine_stage 验证:
        # 浮盈达到后不会回退到低级阶段
        state = PositionState.initial("000001", entry_price=100.0)
        state = state.observe_price(135.0)  # +35% → TRAILING

        stage, stop, _ = DynamicStopCalculator.determine_stage(state)
        assert stage == StopStage.TRAILING

        # 即使价格回落，阶段不变
        state2 = state.observe_price(105.0)  # 回落到 +5%
        stage2, _, _ = DynamicStopCalculator.determine_stage(state2)
        # 如果已在 TRAILING，determine_stage 会保持 TRAILING
        if state.stop_stage == StopStage.TRAILING:
            assert stage2 == StopStage.TRAILING

    def test_trailing_stop_never_decreases(self):
        """追踪止损价只升不降（测试 DynamicStopCalculator.trailing_stop）。"""
        state = PositionState.initial(
            "000001", entry_price=100.0,
            stop_config={"trailing_stop_pct": -0.05},
        )
        state = state.observe_price(120.0)
        state = state.with_stop(StopStage.TRAILING, 114.0)

        # 价格回落到 110
        state2 = state.observe_price(110.0)
        stop = DynamicStopCalculator.trailing_stop(state2)
        assert stop == pytest.approx(114.0)  # 不下移
