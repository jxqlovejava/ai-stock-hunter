# -*- coding: utf-8 -*-
"""全量回测脚本 — 明天下载完成后运行。

用法:
  .venv/bin/python src/backtest/full_backtest.py
"""

import itertools
from pathlib import Path

import pandas as pd

from src.backtest.engine import BacktestEngine
from src.backtest.mvp2_strategy import MVP2Strategy

CACHE = Path(__file__).resolve().parent.parent.parent / "data" / "kline_cache"
START = "2015-01-01"
END = "2025-12-31"
FMT = "20150101_20251231"


def load_all():
    codes = sorted(
        set(
            f.stem.split("_")[0]
            for f in CACHE.glob(f"*_{FMT}_daily.csv")
            if not f.stem.startswith("IDX") and len(f.stem.split("_")[0]) == 6
        )
    )
    loaded = []
    for code in codes:
        f = CACHE / f"{code}_{FMT}_daily.csv"
        df = pd.read_csv(f, parse_dates=["date"], index_col="date")
        if len(df) < 500:
            continue
        close = df["close"]
        rh = close.rolling(252).max()
        rl = close.rolling(252).min()
        df["pe_pct"] = ((close - rl) / (rh - rl).clip(lower=0.01) * 100).fillna(50)
        df["roe"] = (close.pct_change(252) * 100).fillna(0)
        df["momentum"] = (close.pct_change(21) * 100).fillna(0)
        loaded.append((code, df))
    return loaded


def main():
    loaded = load_all()
    print(f"全量: {len(loaded)} 只")

    results = []
    # Fine grid around best config
    for pe in [75, 78]:
        for mp in [8, 10, 12]:
            for br in [0.85, 0.88, 0.92]:
                for sl in [-0.22, -0.24]:
                    e = BacktestEngine(1_000_000)
                    e.add_strategy(
                        MVP2Strategy,
                        max_positions=mp,
                        rebalance_days=10,
                        pe_pct_threshold=pe,
                        base_stop_loss=sl,
                        use_market_timing=True,
                        ma_period=60,
                        bear_reduce=br,
                    )
                    for code, df in loaded:
                        e.add_data(code, df)
                    try:
                        r = e.run(start=START, end=END)
                        label = f"PE<{pe} x{mp} br={br:.0%} sl={sl:.0%}"
                        results.append((r.sharpe_ratio, r.annual_return, r.total_trades, label))
                        print(f"  {label}: 夏普={r.sharpe_ratio:.3f} 年化={r.annual_return:.2%}")
                    except Exception as ex:
                        print(f"  {label}: ERROR {ex}")

    results.sort(key=lambda x: x[0], reverse=True)
    print(f"\n{'='*60}")
    print(f"TOP 5 (共 {len(loaded)} 只):")
    for sh, ar, tr, label in results[:5]:
        print(f"  {label}: 夏普={sh:.3f} 年化={ar:.2%} 交易={tr}")

    best = results[0]
    print(f"\n🏆 最优: {best[3]}")
    print(f"   夏普={best[0]:.3f} 年化={best[1]:.2%}")
    print(f"   vs CSI300 5.46%: 超额={(best[1] - 0.0546):.2%}")


if __name__ == "__main__":
    main()
