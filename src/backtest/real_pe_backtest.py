# -*- coding: utf-8 -*-
"""真实 PE 分位回测 — 使用 baostock PE TTM 数据。

用法:
  .venv/bin/python src/backtest/real_pe_backtest.py
"""

import pandas as pd, numpy as np
from pathlib import Path
from src.backtest.engine import BacktestEngine
from src.backtest.mvp2_strategy import MVP2Strategy

CACHE = Path(__file__).resolve().parent.parent.parent / "data" / "kline_cache"
START = "2015-01-01"
END = "2025-12-31"
FMT = "20150101_20251231"


def load_real_pe():
    """加载所有含 PE TTM 数据的股票，计算每日 PE 分位。"""
    codes = []
    for f in CACHE.glob(f"*_{FMT}_daily.csv"):
        if f.stem.startswith("IDX"):
            continue
        code = f.stem.split("_")[0]
        if len(code) != 6:
            continue
        df = pd.read_csv(f, parse_dates=["date"], index_col="date")
        if "pe_ttm" not in df.columns or len(df) < 500:
            continue
        # Only use stocks with sufficient PE data
        pe_valid = df["pe_ttm"].dropna()
        if len(pe_valid) < 200:
            continue
        codes.append(code)

    print(f"PE TTM 可用: {len(codes)} 只")

    # Collect all PE TTM data for percentile calculation
    all_dates = set()
    stock_pe = {}
    stock_data = {}

    for code in codes:
        f = CACHE / f"{code}_{FMT}_daily.csv"
        df = pd.read_csv(f, parse_dates=["date"], index_col="date")
        if len(df) < 500:
            continue

        # Use real PE TTM for value factor
        df["pe_ttm"] = pd.to_numeric(df["pe_ttm"], errors="coerce")
        df["pb"] = pd.to_numeric(df.get("pb", 0), errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce")

        # Filter date range
        df = df[START:END]
        if len(df) < 200:
            continue

        # PE TTM: NaN means negative earnings -> most expensive
        pe = df["pe_ttm"].copy()
        all_dates.update(pe.dropna().index.tolist())
        stock_pe[code] = pe
        stock_data[code] = df

    # Calculate daily PE percentile
    print(f" 计算 PE 分位... 覆盖 {len(all_dates)} 个交易日")
    pe_pct = {}
    for code in stock_pe:
        pe_series = stock_pe[code].copy()
        pct = pd.Series(50.0, index=pe_series.index)
        for date in pe_series.dropna().index:
            day_pes = []
            for c, s in stock_pe.items():
                v = s.get(date)
                if v is not None and v > 0:
                    day_pes.append(v)
            if day_pes:
                current_pe = pe_series.get(date)
                if current_pe is not None and current_pe > 0 and len(day_pes) >= 20:
                    rank = sum(1 for p in day_pes if p < current_pe)
                    pct[date] = rank / len(day_pes) * 100
        pe_pct[code] = pct

    # Prepare data for backtest engine
    loaded = []
    for code in codes:
        df = stock_data[code].copy()
        df["pe_pct"] = pe_pct.get(code, pd.Series(50, index=df.index))
        df["pe_pct"] = df["pe_pct"].fillna(method="ffill").fillna(50)
        # ROE proxy from PE = 1/PE (higher PE = lower ROE, but not exactly)
        df["roe"] = (1 / df["pe_ttm"].clip(lower=1) * 100).fillna(0)
        df["momentum"] = (df["close"].pct_change(21) * 100).fillna(0)
        loaded.append((code, df))

    return loaded


def main():
    loaded = load_real_pe()
    print(f"\n{len(loaded)} 只, 开始网格搜索...")

    results = []
    for pe in [30, 40, 50, 60, 70]:
        for br in [0.85, 0.88]:
            e = BacktestEngine(1_000_000)
            e.add_strategy(
                MVP2Strategy,
                max_positions=8,
                rebalance_days=10,
                pe_pct_threshold=pe,
                base_stop_loss=-0.22,
                use_market_timing=True,
                ma_period=60,
                bear_reduce=br,
            )
            for code, df in loaded:
                e.add_data(code, df)
            r = e.run(start=START, end=END)

            def sf(v, d=0.0):
                if isinstance(v, complex):
                    return d
                try:
                    fv = float(v)
                    return d if fv != fv else fv
                except:
                    return d

            sh = sf(r.sharpe_ratio)
            ar = sf(r.annual_return)
            label = f"PE<{pe}% br={br:.0%}"
            results.append((sh, ar, r.total_trades, label))
            print(f"  {label}: 夏普={sh:.3f} 年化={ar:.2%} 交易={r.total_trades}")

    results.sort(key=lambda x: x[0], reverse=True)
    if results:
        print(f"\n🏆 TOP ({len(loaded)}只):")
        for sh, ar, tr, label in results[:5]:
            print(f"  {label}: 夏普={sh:.3f} 年化={ar:.2%} 交易={tr}")


if __name__ == "__main__":
    main()
