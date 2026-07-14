# -*- coding: utf-8 -*-
"""SwingOverlay / board_lot — V1 解套改写 + V2 分桶做 T + 一手约束。"""

from __future__ import annotations

import pytest

from src.strategy.board_lot import (
    BOARD_LOT,
    can_partial_reduce,
    floor_to_lot,
    resolve_buy_quantity,
    resolve_sell_quantity,
)
from src.strategy.swing_overlay import (
    OverlayAction,
    OverlayMarketContext,
    PositionBucketView,
    SwingOverlayConfig,
    SwingOverlayEngine,
    format_decision,
)


# ---------------------------------------------------------------------------
# board_lot
# ---------------------------------------------------------------------------


class TestBoardLot:
    def test_floor_to_lot(self):
        assert floor_to_lot(250) == 200
        assert floor_to_lot(99) == 0
        assert floor_to_lot(100) == 100
        assert floor_to_lot(0) == 0

    def test_can_partial_reduce_requires_two_lots(self):
        assert can_partial_reduce(100) is False
        assert can_partial_reduce(200) is True
        assert can_partial_reduce(150) is False  # 不足 200

    def test_one_lot_half_reduce_upgrades_to_full(self):
        qty, note = resolve_sell_quantity(100, 50.0)
        assert qty == 100
        assert note == "lot_constraint_full_exit"

    def test_two_lots_half_reduce(self):
        qty, note = resolve_sell_quantity(200, 50.0)
        assert qty == 100
        assert note == "partial_lot_exit"

    def test_full_exit(self):
        qty, note = resolve_sell_quantity(300, 100.0)
        assert qty == 300
        assert note == "full_exit"

    def test_buy_below_lot(self):
        qty, note = resolve_buy_quantity(80)
        assert qty == 0
        assert note == "budget_below_one_lot"

    def test_buy_ok(self):
        qty, note = resolve_buy_quantity(250)
        assert qty == 200
        assert note == "ok"


# ---------------------------------------------------------------------------
# plan buckets
# ---------------------------------------------------------------------------


class TestBucketPlan:
    def setup_method(self):
        self.eng = SwingOverlayEngine()

    def test_plan_respects_single_max(self):
        plan = self.eng.plan_buckets(equity=500_000, price=50.0, target_total_pct=0.50)
        assert plan.core_weight_pct + plan.swing_weight_pct <= 0.20 + 1e-6
        assert plan.total_shares % BOARD_LOT == 0

    def test_plan_zero_price(self):
        plan = self.eng.plan_buckets(500_000, 0, 0.1)
        assert plan.total_shares == 0

    def test_split_existing_one_lot_all_core(self):
        core, swing = self.eng.split_existing(100)
        assert core == 100
        assert swing == 0

    def test_split_existing_multi_lot(self):
        core, swing = self.eng.split_existing(1000)
        assert core + swing == 1000
        assert swing % BOARD_LOT == 0
        assert core >= BOARD_LOT


# ---------------------------------------------------------------------------
# evaluate — V1 structure / stop / no-add
# ---------------------------------------------------------------------------


def _pos(
    shares: int = 100,
    entry: float = 58.851,
    price: float = 52.55,
    stop: float = 53.93,
    equity: float = 500_000,
    core: int | None = None,
    swing: int | None = None,
) -> PositionBucketView:
    if core is None and swing is None:
        core, swing = shares, 0
        if shares >= 200:
            core, swing = int(shares * 0.7) // 100 * 100, 0
            swing = shares - core
    return PositionBucketView(
        symbol="002460",
        name="赣锋锂业",
        total_shares=shares,
        core_shares=core if core is not None else shares,
        swing_shares=swing if swing is not None else 0,
        entry_price=entry,
        current_price=price,
        stop_price=stop,
        equity=equity,
    )


class TestEvaluateV1:
    def setup_method(self):
        self.eng = SwingOverlayEngine()

    def test_stop_hit_exits_full(self):
        pos = _pos(shares=100, price=52.55, stop=53.93)
        ctx = OverlayMarketContext(price=52.55, stop_price=53.93, ma20=63.0)
        d = self.eng.evaluate(pos, ctx)
        assert d.action == OverlayAction.EXIT
        assert d.quantity == 100
        assert d.rule == "stop_hit"
        assert d.urgency == "HIGH"

    def test_one_lot_structure_break_full_exit(self):
        """1 手 + 结构破位（止损未破）→ 手数约束全平。"""
        pos = _pos(shares=100, price=55.0, stop=50.0, entry=58.0)
        ctx = OverlayMarketContext(
            price=55.0,
            stop_price=50.0,
            ma20=63.0,
            structure_broken=True,
        )
        d = self.eng.evaluate(pos, ctx)
        assert d.action == OverlayAction.EXIT
        assert d.quantity == 100
        assert d.rule == "structure_break_full"

    def test_two_lot_structure_break_partial(self):
        pos = _pos(shares=200, price=55.0, stop=50.0, entry=58.0, core=200, swing=0)
        ctx = OverlayMarketContext(price=55.0, stop_price=50.0, ma20=63.0)
        d = self.eng.evaluate(pos, ctx)
        assert d.action == OverlayAction.REDUCE
        assert d.quantity == 100
        assert d.rule == "structure_break_partial"

    def test_no_add_to_loser_near_support(self):
        pos = _pos(shares=200, price=50.0, entry=58.0, stop=40.0, core=100, swing=100)
        # pnl ~ -13.8%
        ctx = OverlayMarketContext(
            price=50.0,
            stop_price=40.0,
            ma20=48.0,  # not broken
            near_support=True,
            pipeline_score=60,
            pipeline_action="HOLD",
            structure_broken=False,
        )
        d = self.eng.evaluate(pos, ctx)
        assert d.action == OverlayAction.BLOCKED
        assert d.rule == "no_add_to_loser"
        assert d.quantity == 0


# ---------------------------------------------------------------------------
# evaluate — V2 swing
# ---------------------------------------------------------------------------


class TestEvaluateV2:
    def setup_method(self):
        self.eng = SwingOverlayEngine()

    def test_swing_sell_at_resistance(self):
        pos = _pos(shares=500, price=60.0, entry=55.0, stop=50.0, core=300, swing=200)
        ctx = OverlayMarketContext(
            price=60.0,
            stop_price=50.0,
            ma20=50.0,
            near_resistance=True,
            structure_broken=False,
            swing_shares_sellable=200,
        )
        d = self.eng.evaluate(pos, ctx)
        assert d.action == OverlayAction.SWING_SELL
        assert d.quantity == 200
        assert d.rule == "swing_sell_resistance"

    def test_swing_buy_at_support_with_budget(self):
        # small existing, large equity → room for swing buy
        pos = _pos(shares=200, price=50.0, entry=49.0, stop=45.0, core=200, swing=0)
        ctx = OverlayMarketContext(
            price=50.0,
            stop_price=45.0,
            ma20=48.0,
            near_support=True,
            structure_broken=False,
            pipeline_score=60,
            pipeline_action="HOLD",
            swing_trades_today=0,
        )
        d = self.eng.evaluate(pos, ctx)
        assert d.action == OverlayAction.SWING_BUY
        assert d.quantity >= 100
        assert d.quantity % 100 == 0
        assert d.rule == "swing_buy_support"

    def test_swing_buy_blocked_day_limit(self):
        pos = _pos(shares=200, price=50.0, entry=49.0, stop=45.0, core=200, swing=0)
        ctx = OverlayMarketContext(
            price=50.0,
            stop_price=45.0,
            ma20=48.0,
            near_support=True,
            structure_broken=False,
            pipeline_score=60,
            swing_trades_today=2,
        )
        d = self.eng.evaluate(pos, ctx)
        assert d.action == OverlayAction.BLOCKED
        assert d.rule == "swing_day_limit"

    def test_hold_when_quiet(self):
        pos = _pos(shares=200, price=55.0, entry=54.0, stop=50.0, core=200, swing=0)
        ctx = OverlayMarketContext(
            price=55.0,
            stop_price=50.0,
            ma20=50.0,
            structure_broken=False,
        )
        d = self.eng.evaluate(pos, ctx)
        assert d.action == OverlayAction.HOLD
        assert d.rule == "hold"


class TestFormatAndDict:
    def test_format_and_to_dict(self):
        eng = SwingOverlayEngine()
        pos = _pos(shares=100, price=52.0, stop=53.0)
        ctx = OverlayMarketContext(price=52.0, stop_price=53.0)
        d = eng.evaluate(pos, ctx)
        text = format_decision(d)
        assert "002460" in text
        assert d.to_dict()["action"] == "EXIT"


class TestGanfengPaperScenario:
    """与真实持仓一致的回归：100 股、破止损 → 只能全出。"""

    def test_ganfeng_one_lot_stop(self):
        eng = SwingOverlayEngine()
        pos = PositionBucketView(
            symbol="002460",
            name="赣锋锂业",
            total_shares=100,
            core_shares=100,
            swing_shares=0,
            entry_price=58.851,
            current_price=52.55,
            stop_price=53.93,
            equity=500_000,
        )
        ctx = OverlayMarketContext(
            price=52.55,
            ma20=63.58,
            stop_price=53.93,
        )
        d = eng.evaluate(pos, ctx)
        assert d.action == OverlayAction.EXIT
        assert d.quantity == 100
        # 半仓路径不存在
        assert d.quantity % 100 == 0
