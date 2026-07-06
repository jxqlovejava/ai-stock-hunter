# -*- coding: utf-8 -*-
"""VibeBacktestEngine 单元测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from src.backtest.engine_v2 import VibeBacktestEngine
from src.data.schema import Quote
from src.data.source_citation import SourceCitation


def _quote(sym: str, **kwargs) -> Quote:
    defaults = {
        "symbol": sym,
        "name": sym,
        "price": 100.0,
        "source": "test",
        "listing_date": datetime.now() - timedelta(days=100),
        "turnover": 100_000_000,
        "is_st": False,
        "suspended": False,
    }
    defaults.update(kwargs)
    return Quote(**defaults)


def _make_ohlcv(prices: list[float], start_date: str = "2025-01-01") -> pd.DataFrame:
    dates = pd.date_range(start_date, periods=len(prices))
    return pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1000] * len(prices),
        },
        index=dates,
    )


def test_engine_v2_runs_and_produces_metrics():
    data = {
        "600519": _make_ohlcv([100.0, 101.0, 102.0, 103.0]),
        "000001": _make_ohlcv([10.0, 10.5, 11.0, 11.5]),
    }
    quotes = {sym: _quote(sym) for sym in data}
    engine = VibeBacktestEngine(initial_cash=1_000_000)
    result = engine.run(
        symbols=list(data.keys()),
        start_date="20250101",
        end_date="20250104",
        data_map=data,
        quotes=quotes,
    )
    assert result.total_trades >= 0
    assert result.final_value > 0
    assert result.data_citation is not None
    assert result.signal_citation is not None


def test_engine_v2_blocks_with_low_confidence_data():
    data = {
        "600519": _make_ohlcv([100.0, 101.0]),
    }
    low_conf = SourceCitation(
        provider="akshare", field="close", confidence=0.4, nature="fact", source_tier="T2"
    )
    data["600519"].attrs["source_citation"] = low_conf
    quotes = {"600519": _quote("600519")}

    engine = VibeBacktestEngine(initial_cash=1_000_000)
    result = engine.run(
        symbols=list(data.keys()),
        start_date="20250101",
        end_date="20250102",
        data_map=data,
        quotes=quotes,
    )
    assert result.trading_blocked
    assert "confidence" in result.block_reason
