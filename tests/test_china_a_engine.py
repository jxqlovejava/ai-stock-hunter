# -*- coding: utf-8 -*-
"""ChinaAEngine 单元测试。"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from src.backtest.engines.china_a import ChinaAEngine


@pytest.fixture
def engine():
    return ChinaAEngine({})


def make_bar(close: float, prev_close: float, ts: str = "2025-01-02") -> pd.Series:
    return pd.Series(
        {
            "close": close,
            "prev_close": prev_close,
            "open": close,
            "timestamp": pd.Timestamp(ts),
        }
    )


def test_no_short_selling(engine):
    bar = make_bar(10.0, 9.0)
    assert not engine.can_execute("600519", -1, bar)


def test_can_buy_normal(engine):
    bar = make_bar(9.5, 9.0)
    assert engine.can_execute("600519", 1, bar)


def test_limit_up_buy_blocked(engine):
    # 涨停约 +10%
    bar = make_bar(11.0, 10.0)
    assert not engine.can_execute("600519", 1, bar)


def test_limit_down_sell_blocked(engine):
    bar = make_bar(9.0, 10.0)
    assert not engine.can_execute("600519", 0, bar)


def test_t1_same_day_sell_blocked(engine):
    bar = make_bar(10.0, 10.0)
    engine.positions["600519"] = type("P", (), {"entry_time": pd.Timestamp("2025-01-02")})()
    assert not engine.can_execute("600519", 0, bar)


def test_round_size_100_lot(engine):
    assert engine.round_size(150, 10.0) == 100
    assert engine.round_size(250, 10.0) == 200


def test_commission_buy_no_stamp_tax(engine):
    comm = engine.calc_commission(1000, 10.0, 1, is_open=True)
    assert comm > 0
    # 买入无印花税: max(3,5) + transfer 0.1 = 5.1
    assert comm == 5.0 + 10000 * 0.00001


def test_commission_sell_includes_stamp_tax(engine):
    comm = engine.calc_commission(1000, 10.0, 0, is_open=False)
    # 卖出：佣金最低 5 + 过户费 0.1 + 印花税 0.0005*10000=5
    assert comm == 10.1


def test_apply_slippage_direction(engine):
    assert engine.apply_slippage(10.0, 1) > 10.0
    assert engine.apply_slippage(10.0, -1) < 10.0
