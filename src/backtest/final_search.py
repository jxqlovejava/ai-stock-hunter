# -*- coding: utf-8 -*-
"""最终网格搜索 — 全量缓存数据 + MVP2 最优参数区域。"""

import pandas as pd
from pathlib import Path
from src.backtest.engine import BacktestEngine
from src.backtest.mvp2_strategy import MVP2Strategy

CACHE = Path(__file__).resolve().parent.parent.parent / "data" / "kline_cache"
START = "2015-01-01"
END = "2025-12-31"
FMT = "20150101_20251231"


def load_all():
    codes = sorted(set(
        f.stem.split("_")[0] for f in CACHE.glob(f"*_{FMT}_daily.csv")
        if not f.stem.startswith("IDX")
    ))
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


if __name__ == "__main__":
    loaded = load_all()
    print(f"全量数据: {len(loaded)} 只")

    results = []
    # Fine grid around best params
    for pe in [70, 75, 78, 80]:
        for rbd in [8, 10, 12]:
            for mp in [8, 10, 12]:
                for sl in [-0.20, -0.22, -0.24]:
                    for br in [0.80, 0.85, 0.90]:
                        e = BacktestEngine(1_000_000)
                        e.add_strategy(MVP2Strategy,
                            max_positions=mp, rebalance_days=rbd,
                            pe_pct_threshold=pe, base_stop_loss=sl,
                            use_market_timing=True, ma_period=60,
                            bear_reduce=br)
                        for code, df in loaded:
                            e.add_data(code, df)
                        try:
                            r = e.run(start=START, end=END)
                            results.append((r, {
                                "pe": pe, "rbd": rbd, "mp": mp,
                                "sl": sl, "br": br,
                            }))
                        except Exception:
                            pass

    results.sort(key=lambda x: x[0].sharpe_ratio, reverse=True)

    print(f"\n{'='*70}")
    print(f"TOP 10 (共 {len(results)} 组)")
    print(f"{'='*70}")
    for i, (r, p) in enumerate(results[:10]):
        label = f"PE<{p['pe']} {p['rbd']}d x{p['mp']} sl={p['sl']:.0%} br={p['br']:.0%}"
        print(f"  {i+1}. {label}: 年化={r.annual_return:.2%} 夏普={r.sharpe_ratio:.3f} 交易={r.total_trades}")

    best = results[0]
    print(f"\n🏆 最优: PE<{best[1]['pe']} {best[1]['rbd']}d x{best[1]['mp']} sl={best[1]['sl']:.0%} br={best[1]['br']:.0%}")
    print(f"   年化={best[0].annual_return:.2%} 夏普={best[0].sharpe_ratio:.3f}")
