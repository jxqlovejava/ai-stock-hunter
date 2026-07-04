# -*- coding: utf-8 -*-
"""全面回测: 更多股票 + 基准对比 + 网格搜索。

用法:
  python -m src.backtest.comprehensive
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from .engine import BacktestEngine
from .mvp1_strategy import MVP1Strategy

CACHE = Path(__file__).resolve().parent.parent.parent / "data" / "kline_cache"
CACHE.mkdir(parents=True, exist_ok=True)

START = "2015-01-01"
END = "2025-12-31"
START_FMT = "20150101"
END_FMT = "20251231"


# ---------------------------------------------------------------------------
# 下载
# ---------------------------------------------------------------------------

def download_stock(code: str, retries: int = 3) -> Optional[pd.DataFrame]:
    """下载单只股票 K 线，带重试和本地缓存。"""
    cache_path = CACHE / f"{code}_{START_FMT}_{END_FMT}_daily.csv"
    if cache_path.exists():
        df = pd.read_csv(cache_path, parse_dates=["date"], index_col="date")
        if len(df) > 200:
            return df

    for attempt in range(retries):
        try:
            import akshare as ak
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=START_FMT, end_date=END_FMT,
                adjust="qfq",
            )
            if df is not None and len(df) > 200:
                df = df.rename(columns={
                    "日期": "date", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low", "成交量": "volume",
                })
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")
                df.to_csv(cache_path)
                return df
        except Exception:
            if attempt < retries - 1:
                time.sleep(2)
    return None


def download_index(code: str = "000300", name: str = "沪深300") -> Optional[pd.DataFrame]:
    """下载指数 K 线作为基准。"""
    cache_path = CACHE / f"IDX_{code}_{START_FMT}_{END_FMT}_daily.csv"
    if cache_path.exists():
        return pd.read_csv(cache_path, parse_dates=["date"], index_col="date")

    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol=f"sh{code}" if code.startswith("000") else f"sz{code}")
        if df is not None and len(df) > 200:
            df = df.rename(columns={"date": "date", "close": "close"})
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")
            df.to_csv(cache_path)
            return df
    except Exception:
        pass
    return None


def expand_universe(target: int = 150) -> list[str]:
    """扩展股票池到 target 只。"""
    # 获取已缓存的
    cached = set(f.stem.split("_")[0] for f in CACHE.glob("*.csv") if not f.stem.startswith("IDX"))

    if len(cached) >= target:
        return sorted(cached)[:target]

    # 尝试下载更多
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot()
        all_codes = df["代码"].astype(str).tolist()
        # 优先选沪市主板（6开头）和深市主板（00开头），市值排序
        candidates = [c for c in all_codes if c.startswith(("6", "00")) and c not in cached]
        print(f"  候选池: {len(candidates)} 只 (沪市主板+深市主板)")

        new = 0
        for code in candidates:
            if len(cached) + new >= target:
                break
            df = download_stock(code)
            if df is not None:
                cached.add(code)
                new += 1
                if new % 10 == 0:
                    print(f"  已下载: {len(cached)} 只")
    except Exception as e:
        print(f"  扩展失败: {e}")

    return sorted(cached)[:target]


# ---------------------------------------------------------------------------
# 因子计算
# ---------------------------------------------------------------------------

def prep_factors(df: pd.DataFrame) -> pd.DataFrame:
    """预计算因子列。"""
    close = df["close"]
    rh = close.rolling(252).max()
    rl = close.rolling(252).min()
    denom = (rh - rl).clip(lower=0.01)
    df["pe_pct"] = ((close - rl) / denom * 100).fillna(50)
    df["roe"] = (close.pct_change(252) * 100).fillna(0)
    df["momentum"] = (close.pct_change(21) * 100).fillna(0)
    return df


# ---------------------------------------------------------------------------
# 网格搜索
# ---------------------------------------------------------------------------

@dataclass
class GridResult:
    params: dict
    annual_return: float = 0
    sharpe: float = 0
    max_drawdown: float = 0
    trades: int = 0
    final_value: float = 0


def grid_search(
    codes: list[str],
    pe_thresholds: list[int] = None,
    rebalance_days: list[int] = None,
    max_pos: list[int] = None,
) -> list[GridResult]:
    """网格搜索最优参数组合。"""
    if pe_thresholds is None:
        pe_thresholds = [30, 50, 70]
    if rebalance_days is None:
        rebalance_days = [10, 21, 63]
    if max_pos is None:
        max_pos = [10, 20]

    results = []
    total = len(pe_thresholds) * len(rebalance_days) * len(max_pos)

    for i, pe in enumerate(pe_thresholds):
        for rbd in rebalance_days:
            for mp in max_pos:
                engine = BacktestEngine(initial_cash=1_000_000)
                engine.add_strategy(
                    MVP1Strategy,
                    max_positions=mp,
                    rebalance_days=rbd,
                    pe_pct_threshold=pe,
                )
                for code in codes:
                    f = CACHE / f"{code}_{START_FMT}_{END_FMT}_daily.csv"
                    if f.exists():
                        df = pd.read_csv(f, parse_dates=["date"], index_col="date")
                        if len(df) >= 500:
                            df = prep_factors(df)
                            engine.add_data(code, df)

                try:
                    r = engine.run(start=START, end=END)
                    results.append(GridResult(
                        params={"pe_pct_threshold": pe, "rebalance_days": rbd, "max_positions": mp},
                        annual_return=r.annual_return,
                        sharpe=r.sharpe_ratio,
                        max_drawdown=r.max_drawdown,
                        trades=r.total_trades,
                        final_value=r.final_value,
                    ))
                except Exception:
                    results.append(GridResult(
                        params={"pe_pct_threshold": pe, "rebalance_days": rbd, "max_positions": mp},
                    ))

                progress = len(results)
                params_str = f"PE<{pe} rbd={rbd}d pos={mp}"
                if results[-1].trades > 0:
                    print(f"  [{progress}/{total}] {params_str}: 年化={results[-1].annual_return:.1%} 夏普={results[-1].sharpe:.2f}")
                else:
                    print(f"  [{progress}/{total}] {params_str}: 失败")

    results.sort(key=lambda x: x.sharpe, reverse=True)
    return results


# ---------------------------------------------------------------------------
# 基准对比
# ---------------------------------------------------------------------------

def benchmark_compare(strategy_result, bench_code: str = "000300"):
    """对比策略 vs 基准指数。"""
    bench = download_index(bench_code)
    if bench is None or "close" not in bench.columns:
        return None

    bench_start = bench["close"].iloc[0]
    bench_end = bench["close"].iloc[-1]
    bench_return = (bench_end / bench_start - 1)
    bench_years = (bench.index[-1] - bench.index[0]).days / 365.25
    bench_annual = (1 + bench_return) ** (1 / bench_years) - 1 if bench_years > 0 else 0

    return {
        "benchmark": bench_code,
        "bench_annual": bench_annual,
        "strategy_annual": strategy_result.annual_return,
        "excess": strategy_result.annual_return - bench_annual,
        "bench_return": bench_return,
        "strategy_return": strategy_result.total_return,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("全面回测")
    print("=" * 60)

    # 1. 下载基准
    print("\n1. 下载基准指数...")
    bench = download_index("000300")
    if bench is not None:
        bench_start = bench["close"].iloc[0]
        bench_end = bench["close"].iloc[-1]
        years = (bench.index[-1] - bench.index[0]).days / 365.25
        bench_annual = (bench_end / bench_start) ** (1 / years) - 1
        print(f"   沪深300: {bench_start:.0f} → {bench_end:.0f}, 年化 {bench_annual:.2%}")

    # 2. 扩展股票池
    print(f"\n2. 扩展股票池 (目标 150 只)...")
    codes = expand_universe(target=150)
    print(f"   可用: {len(codes)} 只")

    # 3. 网格搜索
    print(f"\n3. 网格搜索 (3×3×2=18 组合)...")
    results = grid_search(
        codes,
        pe_thresholds=[30, 50, 70],
        rebalance_days=[10, 21, 63],
        max_pos=[10, 20],
    )

    # 4. 输出最优结果
    print(f"\n4. 最优参数 (按夏普排序):")
    print(f"{'排名':<4} {'PE阈值':<6} {'调仓':<6} {'持仓数':<6} {'年化':<8} {'夏普':<8} {'回撤':<8} {'交易':<6}")
    print("-" * 60)
    for i, r in enumerate(results[:10]):
        p = r.params
        print(f"{i+1:<4} {p['pe_pct_threshold']:<6} {p['rebalance_days']}d{'':<3} {p['max_positions']:<6} {r.annual_return:<8.1%} {r.sharpe:<8.2f} {r.max_drawdown:<8.1f}% {r.trades:<6}")

    # 5. 基准对比
    if bench is not None and results:
        best = results[0]
        print(f"\n5. 基准对比:")
        print(f"   沪深300 年化: {bench_annual:.2%}")
        print(f"   最优策略年化: {best.annual_return:.2%}")
        print(f"   超额收益:     {(best.annual_return - bench_annual):.2%}")
        print(f"   策略总收益:   {best.final_value:,.0f} (初始 1,000,000)")

    print("\n" + "=" * 60)
    print("完成")
