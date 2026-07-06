# -*- coding: utf-8 -*-
"""AShareHardGuard 单元测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.backtest.guards import AShareHardGuard
from src.data.schema import Quote


@pytest.fixture
def guard():
    return AShareHardGuard()


def quote_factory(**kwargs) -> Quote:
    defaults = {
        "symbol": "600519",
        "name": "茅台",
        "price": 100.0,
        "source": "test",
    }
    defaults.update(kwargs)
    return Quote(**defaults)


def test_st_blocked(guard):
    q = quote_factory(is_st=True)
    assert not guard.is_eligible("600519", q)
    assert "ST" in guard.last_flags()[0]


def test_suspended_blocked(guard):
    q = quote_factory(suspended=True)
    assert not guard.is_eligible("600519", q)


def test_too_new_listing_blocked(guard):
    q = quote_factory(listing_date=datetime.now() - timedelta(days=30))
    assert not guard.is_eligible("600519", q)


def test_low_turnover_blocked(guard):
    q = quote_factory(turnover=10_000_000)
    assert not guard.is_eligible("600519", q)


def test_normal_pass(guard):
    q = quote_factory(
        listing_date=datetime.now() - timedelta(days=100),
        turnover=100_000_000,
        is_st=False,
        suspended=False,
    )
    assert guard.is_eligible("600519", q)


def test_limit_down_bar_blocked(guard):
    q = quote_factory()
    bar = pd.Series({"close": 9.0, "prev_close": 10.0, "open": 9.0})
    assert not guard.is_eligible("600519", q, bar)
