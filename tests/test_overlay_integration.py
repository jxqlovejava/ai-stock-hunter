# -*- coding: utf-8 -*-
"""overlay_integration — paper / 回测 / monitor 适配层测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from src.strategy.overlay_integration import (
    OverlayEvalInput,
    evaluate_overlay,
    decision_to_paper_order,
    adjust_target_weights_with_overlay,
    wrap_signal_engine_with_overlay,
    position_like_to_input,
)
from src.strategy.swing_overlay import OverlayAction


class TestEvaluateAndPaperOrder:
    def test_stop_hit_to_sell_order(self):
        inp = OverlayEvalInput(
            symbol="002460",
            quantity=100,
            entry_price=58.85,
            current_price=52.55,
            stop_price=53.93,
            equity=500_000,
        )
        d = evaluate_overlay(inp, ma20=63.0)
        assert d.action == OverlayAction.EXIT
        order = decision_to_paper_order(d, name="赣锋锂业", price=52.55, stop_price=53.93)
        assert order is not None
        assert order.action == "sell"
        assert order.quantity == 100
        assert "overlay" in order.reason

    def test_hold_no_order(self):
        inp = OverlayEvalInput(
            symbol="000001",
            quantity=200,
            entry_price=10.0,
            current_price=10.5,
            stop_price=9.0,
            equity=500_000,
        )
        d = evaluate_overlay(inp, ma20=10.0, structure_broken=False)
        assert d.action == OverlayAction.HOLD
        assert decision_to_paper_order(d, price=10.5) is None

    def test_position_like_from_dict(self):
        inp = position_like_to_input(
            {
                "symbol": "600519",
                "quantity": 100,
                "entry_price": 1500,
                "last_price": 1480,
                "stop_price": 1400,
                "name": "茅台",
            },
            equity=1_000_000,
        )
        assert inp.symbol == "600519"
        assert inp.current_price == 1480


class TestBacktestWeightAdjust:
    def _synthetic_crash(self) -> dict[str, pd.DataFrame]:
        # 40 日：前 25 日 100 附近，后 15 日崩到 70（破止损与 MA20）
        idx = pd.date_range("2025-01-01", periods=40, freq="B")
        closes = [100.0] * 25 + [90 - i for i in range(15)]
        df = pd.DataFrame(
            {
                "open": closes,
                "high": [c + 1 for c in closes],
                "low": [c - 1 for c in closes],
                "close": closes,
                "volume": [1e6] * 40,
            },
            index=idx,
        )
        return {"000001": df}

    def test_overlay_forces_exit_on_crash(self):
        data_map = self._synthetic_crash()
        dates = data_map["000001"].index
        base = pd.DataFrame(1.0, index=dates, columns=["000001"])
        adj = adjust_target_weights_with_overlay(
            data_map, base, initial_stop_pct=0.08,
        )
        # 后期应出现 0 权重（清仓）
        assert (adj["000001"].iloc[-5:] == 0).any() or adj["000001"].iloc[-1] < 1.0

    def test_wrap_signal_engine(self):
        data_map = self._synthetic_crash()

        def base(dm):
            dates = sorted(set().union(*(df.index for df in dm.values())))
            w = pd.DataFrame(1.0, index=dates, columns=sorted(dm.keys()))
            return w

        wrapped = wrap_signal_engine_with_overlay(base, initial_stop_pct=0.08)
        w = wrapped(data_map)
        assert not w.empty
        assert "000001" in w.columns
