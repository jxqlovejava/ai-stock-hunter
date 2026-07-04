"""Factor Screening Strategy — end-to-end integration demo.

Exercises every capability delivered in the factor screening feature:

  * ``universe_list_indexes()`` — built-in index registry (CSI300, CSI500, ...)
  * ``register_index()`` — registering a custom index (synthetic mode)
  * ``universe_set(type="index")`` — resolving constituents via an index key
  * ``resolve_alias()`` — mapping Chinese names to canonical indicators
  * ``get_indicator_metadata()`` — Agent-readable metadata for indicators
  * ``universe_set(type="filter")`` — screening with audit table output
  * ``financial_download`` with PE, PB, ROA on EastMoney (live mode only)

Test case:
    "从沪深300中选择 ROE>15, PB<10, 动量>0 的股票构成组合"

By default, generates synthetic data and registers it as a custom index so the
demo runs without network access. Use ``--live`` to fetch real constituents and
financial data from AkShare / EastMoney.

Usage:
    uv run python examples/strategies/factor_screen.py
    uv run python examples/strategies/factor_screen.py --live
    uv run python examples/strategies/factor_screen.py --roe 20 --pb 5
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from oxq.core.aliases import resolve_alias
from oxq.core.registry import get_indicator_metadata, list_indicators
from oxq.tools.universe import universe_list_indexes, universe_set
from oxq.universe.index import register_index

# ── Config ──────────────────────────────────────────────────────────────────

START = "2024-01-01"
END = "2025-03-31"
MOMENTUM_PERIOD = 20
INITIAL_CASH = 1_000_000.0

# Simulated CSI300 subset with realistic financial profiles
STOCK_PROFILES = {
    "600519": {"name": "贵州茅台", "roe": 36.0, "pb": 12.5, "drift": 0.0003},
    "000858": {"name": "五粮液",  "roe": 25.0, "pb": 7.8,  "drift": 0.0002},
    "601318": {"name": "中国平安", "roe": 12.0, "pb": 1.1,  "drift": -0.0001},
    "600036": {"name": "招商银行", "roe": 16.5, "pb": 0.8,  "drift": 0.0001},
    "000333": {"name": "美的集团", "roe": 22.0, "pb": 4.5,  "drift": 0.0002},
    "600276": {"name": "恒瑞医药", "roe": 18.0, "pb": 8.2,  "drift": 0.0001},
    "601012": {"name": "隆基绿能", "roe": 8.0,  "pb": 1.5,  "drift": -0.0002},
    "002714": {"name": "牧原股份", "roe": 5.0,  "pb": 3.2,  "drift": -0.0003},
    "600900": {"name": "长江电力", "roe": 17.0, "pb": 3.8,  "drift": 0.0002},
    "000001": {"name": "平安银行", "roe": 10.0, "pb": 0.5,  "drift": 0.0},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Factor screening strategy demo")
    parser.add_argument("--live", action="store_true",
                        help="Use live CSI300 constituents + EastMoney financials")
    parser.add_argument("--live-limit", type=int, default=20,
                        help="Max live symbols to download (default 20)")
    parser.add_argument("--roe", type=float, default=15.0, help="ROE > threshold")
    parser.add_argument("--pb", type=float, default=10.0, help="PB < threshold")
    parser.add_argument("--momentum", type=float, default=0.0, help="Momentum > threshold")
    return parser.parse_args()


# ── Feature showcases ──────────────────────────────────────────────────────


def showcase_index_registry() -> None:
    """Call universe_list_indexes() and print the built-in index registry."""
    result = universe_list_indexes()
    print("Built-in indexes (universe_list_indexes):")
    for idx in result["indexes"]:
        print(f"  {idx['key']:<10} {idx['code']:<8} {idx['name']:<12} (source: {idx['source']})")


def showcase_aliases() -> None:
    """Demonstrate resolve_alias() for Chinese indicator names."""
    samples = ["市净率", "市盈率", "动量", "净资产收益率", "ROE", "custom_factor"]
    print("\nChinese alias resolution (resolve_alias):")
    for name in samples:
        print(f"  {name:<12} -> {resolve_alias(name)}")


def showcase_indicator_metadata(names: list[str]) -> None:
    """Print metadata for given indicators via get_indicator_metadata()."""
    print("\nIndicator metadata (get_indicator_metadata):")
    for name in names:
        info = get_indicator_metadata(name)
        if info is None:
            print(f"  {name}: (no metadata registered)")
            continue
        print(f"  {name:<10} [{info['category']:<10}] {info['source_type']:<8} — {info['description']}")


# ── Step 1: Data + Custom Index Registration ──────────────────────────────


def generate_synthetic_data(data_dir: Path) -> list[str]:
    """Generate synthetic OHLCV + inject financial indicators, write parquet files."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range(START, END)
    momentum_ind = list_indicators()["Momentum"]()
    symbols = list(STOCK_PROFILES.keys())

    for sym, profile in STOCK_PROFILES.items():
        n = len(dates)
        returns = rng.normal(profile["drift"], 0.02, n)
        prices = 100.0 * np.exp(np.cumsum(returns))

        df = pd.DataFrame(
            {
                "open": prices * (1 + rng.normal(0, 0.005, n)),
                "high": prices * (1 + abs(rng.normal(0, 0.01, n))),
                "low": prices * (1 - abs(rng.normal(0, 0.01, n))),
                "close": prices,
                "volume": rng.integers(1_000_000, 50_000_000, n),
                "roe": profile["roe"],
                "pb": profile["pb"],
            },
            index=dates,
        )
        df.index.name = "date"
        df["momentum"] = momentum_ind.compute(df, column="close", period=MOMENTUM_PERIOD)

        df.to_parquet(data_dir / f"{sym}.parquet")

    return symbols


def register_synthetic_index(symbols: list[str]) -> str:
    """Register the synthetic universe as a custom index so universe_set(type='index') works."""
    key = "demo_csi300"
    register_index(
        key=key,
        code="DEMO",
        name="Demo CSI300 Subset",
        fetch_fn=lambda _code: symbols,
        source="synthetic",
    )
    return key


def load_live_universe(limit: int) -> list[str]:
    """Fetch CSI300 constituents via universe_set(type='index') and cap to limit."""
    result = universe_set(type="index", code="csi300")
    if "error" in result:
        raise RuntimeError(f"CSI300 fetch failed: {result['error']}")
    return result["symbols"][:limit]


def download_live_data(symbols: list[str], data_dir: Path) -> list[str]:
    """Download OHLCV + financial data (roe, pb, pe_ttm, roa) for each symbol.

    Writes enriched parquet files (OHLCV + forward-filled financials + momentum)
    into ``data_dir`` so universe_set(type='filter') can read them.
    """
    from oxq.data import AkShareDownloader
    from oxq.data.factors import (
        EastMoneyFetcher,
        FactorDownloader,
        resolve_factor_dir,
    )

    dl = AkShareDownloader()
    fetcher = EastMoneyFetcher()
    fdl = FactorDownloader(fetcher, sub="financial")
    factor_dir = resolve_factor_dir(sub="financial")
    momentum_ind = list_indicators()["Momentum"]()

    enriched: list[str] = []
    for sym in symbols:
        try:
            price_path = dl.download(sym, START, END)
        except Exception as exc:
            print(f"    OHLCV skip {sym}: {exc}")
            continue
        ohlcv = pd.read_parquet(price_path)

        try:
            fdl.download(sym, "2023-01-01", END, indicators=["roe", "pb", "pe_ttm", "roa"])
        except Exception as exc:
            print(f"    Financials skip {sym}: {exc}")
            continue
        fin_path = factor_dir / f"{sym}.parquet"
        if not fin_path.exists():
            continue
        fin = pd.read_parquet(fin_path)

        enriched_df = ohlcv.copy()
        for col in ("roe", "pb", "pe_ttm", "roa"):
            if col in fin.columns:
                enriched_df[col] = fin[col].reindex(enriched_df.index, method="ffill")
        if len(enriched_df) >= MOMENTUM_PERIOD * 2:
            enriched_df["momentum"] = momentum_ind.compute(
                enriched_df, column="close", period=MOMENTUM_PERIOD,
            )

        enriched_df.to_parquet(data_dir / f"{sym}.parquet")
        enriched.append(sym)

    return enriched


# ── Step 2: Screen via universe_set(type='filter') ─────────────────────────


def screen(
    symbols: list[str],
    data_dir: Path,
    roe_min: float,
    pb_max: float,
    momentum_min: float,
) -> dict:
    """Call universe_set(type='filter') to screen — uses the Tool layer, not local logic."""
    # Resolve filter column names via resolve_alias so Chinese input works too
    filters = [
        {"column": resolve_alias("净资产收益率"), "op": ">",  "value": roe_min},
        {"column": resolve_alias("市净率"),       "op": "<",  "value": pb_max},
        {"column": resolve_alias("动量"),         "op": ">",  "value": momentum_min},
    ]
    return universe_set(
        type="filter",
        symbols=symbols,
        filters=filters,
        data_dir=str(data_dir),
        name="factor_screen",
    )


# ── Step 3: Backtest ──────────────────────────────────────────────────────


def run_backtest(screened_symbols: list[str], data_dir: Path) -> None:
    from oxq.core import Engine, Strategy
    from oxq.data import LocalMarketDataProvider
    from oxq.portfolio.optimizers import EqualWeightOptimizer
    from oxq.signals import Threshold
    from oxq.trade import SimBroker
    from oxq.universe import StaticUniverse

    if not screened_symbols:
        print("\n  No stocks passed screening — skipping backtest.")
        return

    strategy = Strategy(
        name="factor_screen_portfolio",
        hypothesis="ROE/PB/Momentum 筛选出的股票等权持有可获得正收益",
        objectives={
            "annualized_return": {"min": 0.0},
            "sharpe_ratio": {"min": 0.0},
        },
        benchmarks=[],
        universe=StaticUniverse(tuple(screened_symbols)),
        signals={
            "active": (Threshold(), {"column": "close", "threshold": 0, "relationship": "gt"}),
        },
        portfolio=EqualWeightOptimizer(),
    )

    result = Engine().run(
        strategy,
        market=LocalMarketDataProvider(data_dir=data_dir),
        broker=SimBroker(),
        start=START,
        end=END,
        initial_cash=INITIAL_CASH,
    )

    print(f"\n{'=' * 72}")
    print("Factor Screen Portfolio — Backtest Results")
    print(f"Universe: {len(screened_symbols)} screened stocks")
    print(f"Period: {START} ~ {END}  |  Init Cash: {INITIAL_CASH:,.0f}")
    print(f"{'=' * 72}")

    rows = [
        ("Total Return", f"{result.total_return():.2%}"),
        ("Ann. Return", f"{result.annualized_return():.2%}"),
        ("Ann. Volatility", f"{result.annualized_volatility():.2%}"),
        ("Sharpe Ratio", f"{result.sharpe_ratio():.2f}"),
        ("Max Drawdown", f"{result.max_drawdown():.2%}"),
        ("Total Trades", f"{len(result.trades)}"),
        ("Final Value", f"{result.equity_curve[-1][1]:,.0f}"),
    ]
    for name, val in rows:
        print(f"  {name:>20}: {val}")


# ── Main ───────────────────────────────────────────────────────────────────


def main() -> None:
    args = parse_args()

    print("=" * 72)
    print("Factor Screening Strategy Demo")
    print(f"Filters: ROE > {args.roe}, PB < {args.pb}, Momentum > {args.momentum}")
    print(f"Period: {START} ~ {END}")
    print("=" * 72)

    # ---- Showcase 1: Built-in index registry --------------------------------
    print()
    showcase_index_registry()

    # ---- Showcase 2: Chinese alias resolution -------------------------------
    showcase_aliases()

    # ---- Showcase 3: Indicator metadata ------------------------------------
    showcase_indicator_metadata(["PE", "PB", "SMA", "RSI", "Momentum"])

    # ---- Step 1: Resolve Universe ------------------------------------------
    print("\n" + "-" * 72)
    if args.live:
        print("Step 1: Resolve CSI300 via universe_set(type='index', code='csi300')")
        symbols = load_live_universe(args.live_limit)
        print(f"  Got {len(symbols)} constituents (limited to {args.live_limit})")

        from oxq.data.loaders import resolve_data_dir
        data_dir = resolve_data_dir()
        print(f"  Data dir: {data_dir}")

        print(f"\nStep 2: Download OHLCV + financials (roe, pb, pe_ttm, roa) for {len(symbols)} symbols")
        symbols = download_live_data(symbols, data_dir)
        print(f"  Enriched parquet files: {len(symbols)}")
    else:
        tmpdir = Path(tempfile.mkdtemp(prefix="oxq_factor_screen_"))
        data_dir = tmpdir
        print(f"Step 1: Generate synthetic data -> {data_dir}")
        symbols = generate_synthetic_data(data_dir)
        print(f"  Generated {len(symbols)} symbols")

        key = register_synthetic_index(symbols)
        print(f"\nStep 2: Register custom index '{key}' via register_index()")
        result = universe_set(type="index", code=key)
        assert "error" not in result, result
        print(f"  universe_set(type='index', code='{key}') -> {result['count']} symbols")

    # ---- Step 3: Screen via Tool -------------------------------------------
    print("\nStep 3: Screen via universe_set(type='filter')")
    print("  Conditions (Chinese names resolved via resolve_alias):")
    print(f"    市净率 -> pb < {args.pb}")
    print(f"    净资产收益率 -> roe > {args.roe}")
    print(f"    动量 -> momentum > {args.momentum}")

    result = screen(symbols, data_dir, args.roe, args.pb, args.momentum)
    if "error" in result:
        print(f"  ERROR: {result['error']}")
        return

    print(f"\n  Base: {result['base_count']} -> Filtered: {result['filtered_count']}")
    print(f"  As of: {result['as_of_date']}")
    print(f"  Source: {result['source']}")

    # Print audit table (from Tool output, not re-implemented locally)
    details = result.get("details", [])
    passing = [d for d in details if d.get("pass")]
    failing = [
        d for d in details
        if not d.get("pass") and d.get("roe") is not None
    ]

    def _fmt(v):
        return f"{v:.3f}" if isinstance(v, float) else ("N/A" if v is None else str(v))

    if passing:
        print(f"\n  Passed ({len(passing)}):")
        print(f"  {'Symbol':<10} {'Name':<12} {'ROE':>8} {'PB':>8} {'Momentum':>10}")
        print(f"  {'-' * 52}")
        for d in passing:
            name = STOCK_PROFILES.get(d["symbol"], {}).get("name", "")
            print(f"  {d['symbol']:<10} {name:<12} {_fmt(d.get('roe')):>8} "
                  f"{_fmt(d.get('pb')):>8} {_fmt(d.get('momentum')):>10}")

    if failing:
        print(f"\n  Failed ({len(failing)}):")
        print(f"  {'Symbol':<10} {'Name':<12} {'ROE':>8} {'PB':>8} {'Momentum':>10}")
        print(f"  {'-' * 52}")
        for d in failing[:10]:
            name = STOCK_PROFILES.get(d["symbol"], {}).get("name", "")
            print(f"  {d['symbol']:<10} {name:<12} {_fmt(d.get('roe')):>8} "
                  f"{_fmt(d.get('pb')):>8} {_fmt(d.get('momentum')):>10}")
        if len(failing) > 10:
            print(f"  ... and {len(failing) - 10} more")

    # ---- Step 4: Backtest ---------------------------------------------------
    print("\nStep 4: Backtest screened portfolio")
    run_backtest(result["symbols"], data_dir)

    print()


if __name__ == "__main__":
    main()
