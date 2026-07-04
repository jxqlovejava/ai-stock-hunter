"""End-to-end test: global rotation ETF strategy built entirely via tools.

Matches examples/strategies/global_rotation_etf.py exactly:
- Universe: 513100.SS, 510300.SS, 518880.SS
- Signal: risk-adjusted momentum (SimpleMomentum / AnnualizedVolatility^0.5) > 0
- Portfolio: TopNRanking by ram score, n=5, max_weight=0.9
- Rules: RebalanceFrequencyRule(interval_days=10)
- Engine: lot_size=100, cash_annual_return=0.025, fill_price_mode=mid, data_start warmup
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oxq.tools import session
from oxq.tools.engine import engine_results, engine_run, engine_trade_list
from oxq.tools.strategy import (
    strategy_add_rule,
    strategy_add_signal,
    strategy_create,
    strategy_inspect,
    strategy_set_portfolio,
    strategy_set_universe,
)


SYMBOLS = ["513100.SS", "510300.SS", "518880.SS"]
DATA_START = "2024-12-01"
START = "2025-01-01"
END = "2026-03-17"


@pytest.fixture(autouse=True)
def _reset_session():
    session.clear()


@pytest.fixture()
def data_dir(tmp_path):
    """Generate synthetic data for 3 ETFs with warmup period."""
    np.random.seed(42)
    dates = pd.bdate_range(DATA_START, END, tz="UTC")
    n = len(dates)

    # 513100: strong uptrend (like Nasdaq)
    closes_513100 = 100 + np.cumsum(np.random.normal(0.4, 1.2, n))
    # 510300: sideways
    closes_510300 = 100 + np.cumsum(np.random.normal(0.0, 0.8, n))
    # 518880: moderate uptrend (like Gold)
    closes_518880 = 100 + np.cumsum(np.random.normal(0.2, 0.6, n))

    for sym, closes in [
        ("513100.SS", closes_513100),
        ("510300.SS", closes_510300),
        ("518880.SS", closes_518880),
    ]:
        df = pd.DataFrame(
            {
                "open": closes * 0.995,
                "high": closes * 1.015,
                "low": closes * 0.985,
                "close": closes,
                "volume": np.random.randint(1_000_000, 10_000_000, n),
            },
            index=dates,
        )
        df.to_parquet(tmp_path / f"{sym}.parquet")

    return str(tmp_path)


def test_global_rotation_etf_e2e(data_dir: str) -> None:
    """Build and backtest global rotation ETF strategy entirely via tools.

    Mirrors examples/strategies/global_rotation_etf.py.
    """

    # -- Phase 0-1: Create strategy ------------------------------------------
    result = strategy_create(
        name="global_rotation_etf",
        hypothesis=(
            "基于风险调整动量（SimpleMomentum(20) / AnnualizedVolatility(20)^0.5）"
            "的全球资产配置策略，在纳指、沪深300、黄金三类资产间轮动，"
            "归一化权重分配，单只上限90%，每10个交易日调仓"
        ),
        objectives={
            "annualized_return": {"min": 0.50},
            "max_drawdown": {"max": -0.20},
        },
        benchmarks=SYMBOLS,
    )
    assert "error" not in result

    # -- Phase 4.2: Set universe ---------------------------------------------
    result = strategy_set_universe(
        strategy="global_rotation_etf",
        type="static",
        symbols=SYMBOLS,
    )
    assert "error" not in result

    # -- Phase 4.3: Add signal with indicators --------------------------------
    # Exactly matches: SimpleMomentum / AnnualizedVolatility^0.5 via PowerRatio
    result = strategy_add_signal(
        strategy="global_rotation_etf",
        name="active",
        type="Threshold",
        params={"column": "ram", "threshold": 0, "relationship": "gt"},
        indicators={
            "mom": {
                "type": "SimpleMomentum",
                "params": {"column": "close", "period": 20},
            },
            "vol": {
                "type": "AnnualizedVolatility",
                "params": {"column": "close", "period": 20},
            },
            "ram": {
                "type": "PowerRatio",
                "params": {"col_a": "mom", "col_b": "vol", "exponent": 0.5},
            },
        },
    )
    assert "error" not in result
    assert "ram" in result["indicators"]

    # -- Phase 4.4: Set portfolio optimizer -----------------------------------
    result = strategy_set_portfolio(
        strategy="global_rotation_etf",
        type="TopNRanking",
        params={
            "score_col": "ram",
            "n": 5,
            "max_weight": 0.90,
        },
    )
    assert "error" not in result

    # -- Phase 4.5: Inspect strategy -----------------------------------------
    inspect = strategy_inspect("global_rotation_etf")
    assert "error" not in inspect
    assert inspect["universe"] == SYMBOLS
    assert "active" in inspect["signals"]
    assert "indicators" in inspect["signals"]["active"]
    assert "ram" in inspect["signals"]["active"]["indicators"]
    assert inspect["portfolio"]["type"] == "TopNRanking"

    # -- Rule: RebalanceFrequencyRule ----------------------------------------
    result = strategy_add_rule(
        strategy="global_rotation_etf",
        name="rebalance_10d",
        type="RebalanceFrequencyRule",
        params={"interval_days": 10},
    )
    assert "error" not in result

    # -- Backtest (matches example params) -----------------------------------
    run_result = engine_run(
        strategy="global_rotation_etf",
        start=START,
        end=END,
        initial_cash=1_000_000.0,
        lot_size=100,
        cash_annual_return=0.025,
        data_start=DATA_START,
        fill_price_mode="mid",
        data_dir=data_dir,
    )
    assert "error" not in run_result, f"engine_run failed: {run_result}"
    run_id = run_result["run_id"]
    assert run_result["total_trades"] > 0

    # -- Check performance ---------------------------------------------------
    perf = engine_results(run_id=run_id)
    assert "error" not in perf
    metrics = perf["metrics"]

    expected_metrics = [
        "total_return", "annualized_return", "annualized_volatility",
        "max_drawdown", "sharpe_ratio", "calmar_ratio", "sortino_ratio",
    ]
    for m in expected_metrics:
        assert m in metrics, f"Missing metric: {m}"

    assert len(perf["objectives_check"]) == 2

    # -- Check trades --------------------------------------------------------
    trades = engine_trade_list(run_id=run_id)
    assert "error" not in trades
    assert trades["total_trades"] > 0
    assert len(trades["trades"]) == trades["total_trades"]

    first_trade = trades["trades"][0]
    assert "symbol" in first_trade
    assert first_trade["symbol"] in SYMBOLS

    # Print results for visibility
    print(f"\n{'='*60}")
    print("Global Rotation ETF Strategy - Backtest Results")
    print(f"{'='*60}")
    print(f"Total Return:          {metrics['total_return']:.2%}")
    print(f"Annualized Return:     {metrics['annualized_return']:.2%}")
    print(f"Annualized Volatility: {metrics['annualized_volatility']:.2%}")
    print(f"Max Drawdown:          {metrics['max_drawdown']:.2%}")
    print(f"Sharpe Ratio:          {metrics['sharpe_ratio']:.2f}")
    print(f"Calmar Ratio:          {metrics['calmar_ratio']:.2f}")
    print(f"Sortino Ratio:         {metrics['sortino_ratio']:.2f}")
    print(f"Total Trades:          {trades['total_trades']}")
    print(f"\nObjectives:")
    for obj in perf["objectives_check"]:
        status = "PASS" if obj["pass"] else "FAIL"
        print(f"  {obj['metric']}: {obj['actual']:.4f} [{status}]")
    print(f"{'='*60}")
