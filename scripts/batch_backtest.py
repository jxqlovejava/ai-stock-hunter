#!/usr/bin/env python3
"""批量回测 — 运行 MVP2+, MVP3, AlphaEvo, MultiFactor, Sector 五种策略。"""

import sys
import time
from pathlib import Path

# 添加项目根
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest.runner import (
    get_hs300_constituents,
    download_universe,
    calculate_pe_percentile_proxy,
    calculate_roe_proxy,
)
from src.backtest.engine import BacktestEngine
from src.backtest.mvp2_plus import MVP2Plus
from src.backtest.mvp3_strategy import MVP3Strategy
from src.backtest.mvp_alpha_evo import MVPAlphaEvo
from src.backtest.mvp_multi_factor import MVPMultiFactor
from src.backtest.mvp_sector import MVPSector
import pandas as pd

STRATEGIES = {
    "MVP2+": {
        "cls": MVP2Plus,
        "params": dict(
            max_positions=10, rebalance_days=10, pe_pct_threshold=75,
            base_stop_loss=-0.22, ma_period=60, bear_reduce=0.85,
            use_market_timing=True,
        ),
    },
    "MVP3": {
        "cls": MVP3Strategy,
        "params": dict(
            max_positions=15, rebalance_days=10, pe_pct_threshold=70,
            base_stop_loss=-0.22, ma_period=60, bear_reduce=0.85,
            use_market_timing=True, min_daily_amount=5e7,
        ),
    },
    "AlphaEvo": {
        "cls": MVPAlphaEvo,
        "params": dict(
            max_positions=8, rebalance_days=10, pe_pct_threshold=75,
            base_stop_loss=-0.22, ma_period=60, bear_reduce=0.85,
            use_market_timing=True,
        ),
    },
    "MultiFactor": {
        "cls": MVPMultiFactor,
        "params": dict(
            max_positions=8, rebalance_days=10, score_threshold=50,
            base_stop_loss=-0.22, ma_period=60, bear_reduce=0.85,
            use_market_timing=True,
        ),
    },
    "Sector": {
        "cls": MVPSector,
        "params": dict(
            max_positions=8, rebalance_days=10, pe_pct_threshold=75,
            base_stop_loss=-0.22, ma_short=60, ma_long=200,
            use_sector_rotation=True, top_sectors=2, sector_lookback=63,
        ),
    },
}

START_DATE = "20190101"
END_DATE = "20241231"
INITIAL_CASH = 1_000_000


def prep_factors(symbols, start_date, end_date):
    """加载数据并计算因子，返回 data_map。"""
    print(f"\n{'='*60}")
    print(f"📥 数据准备: {start_date} → {end_date}")
    print(f"{'='*60}")

    data = download_universe(symbols, start_date, end_date)
    if len(data) < 5:
        raise RuntimeError(f"数据不足: {len(data)} 只")

    print("  计算因子...")
    pe_pcts = calculate_pe_percentile_proxy(data)
    roes = calculate_roe_proxy(data)

    # 找公共日期
    common_dates = None
    for _sym, df in data.items():
        if common_dates is None:
            common_dates = set(df.index)
        else:
            common_dates &= set(df.index)
    common_dates = sorted(common_dates)

    # 注入因子列
    for sym, df in data.items():
        df = df.reindex(common_dates).ffill().dropna()
        if len(df) < 200:
            continue

        pe_pct = pe_pcts.get(sym, pd.Series([50.0] * len(df), index=df.index))
        roe_val = roes.get(sym, pd.Series([10.0] * len(df), index=df.index))

        df["pe_pct"] = pe_pct.reindex(df.index).fillna(50.0)
        df["roe"] = roe_val.reindex(df.index).fillna(10.0)
        df["momentum"] = df["close"].pct_change(21).fillna(0.0) * 100

        # MVP3 多时间框架 PE（用不同回看周期的价格分位）
        for window, col in [(63, "pe63"), (126, "pe126"), (252, "pe252")]:
            roll_max = df["close"].rolling(window).max()
            roll_min = df["close"].rolling(window).min()
            pct = (df["close"] - roll_min) / (roll_max - roll_min + 0.01)
            df[col] = ((1 - pct) * 100).fillna(50.0)

        # 成交额（MVP3 流动性过滤用）
        if "amount" not in df.columns and "volume" in df.columns:
            df["amount"] = (df["volume"] * df["close"]).fillna(0)

        data[sym] = df

    return data, common_dates


def run_one(name: str, cls, params: dict, data_map: dict, common_dates: list):
    """运行单个策略回测，返回 (name, result_or_error)。"""
    print(f"\n  ▶ {name} ...", end=" ", flush=True)
    t0 = time.time()

    try:
        engine = BacktestEngine(initial_cash=INITIAL_CASH)
        engine.add_strategy(cls, **params)

        for sym, df in data_map.items():
            df_aligned = df.reindex(common_dates).ffill().dropna()
            if len(df_aligned) < 200:
                continue
            engine.add_data(code=sym, df=df_aligned)

        n_stocks = len(engine._data_feeds)
        result = engine.run(
            start=f"{START_DATE[:4]}-{START_DATE[4:6]}-{START_DATE[6:]}",
            end=f"{END_DATE[:4]}-{END_DATE[4:6]}-{END_DATE[6:]}",
        )
        elapsed = time.time() - t0
        print(f"✅ ({n_stocks}只, {elapsed:.1f}s)")
        return name, result, n_stocks
    except Exception as e:
        elapsed = time.time() - t0
        print(f"❌ {e} ({elapsed:.1f}s)")
        return name, None, 0


def main():
    print("\n" + "=" * 60)
    print("📊 白泽策略族批量回测")
    print("=" * 60)
    print(f"  期间: {START_DATE} → {END_DATE}")
    print(f"  初始资金: ¥{INITIAL_CASH:,.0f}")
    print(f"  策略: {len(STRATEGIES)} 个")

    # Step 1: 数据准备
    symbols = get_hs300_constituents()
    data_map, common_dates = prep_factors(symbols, START_DATE, END_DATE)
    print(f"\n  ✅ 数据就绪: {len(data_map)} 只, {len(common_dates)} 公共交易日")

    # Step 2: 逐一运行
    results = []
    for name, cfg in STRATEGIES.items():
        r_name, r, n = run_one(name, cfg["cls"], cfg["params"], data_map, common_dates)
        results.append((r_name, r, n))

    # Step 3: 汇总对比
    print("\n" + "=" * 60)
    print("📋 策略回测对比汇总")
    print("=" * 60)
    print(f"{'策略':<16} {'年化收益':>10} {'夏普':>8} {'最大回撤':>10} {'胜率':>8} {'交易次数':>10}")
    print("-" * 64)

    for name, r, n in results:
        if r is not None:
            print(
                f"{name:<16} {r.annual_return:>9.1%} "
                f"{r.sharpe_ratio:>7.2f} {r.max_drawdown:>9.1%} "
                f"{r.win_rate:>7.1%} {r.total_trades:>9}"
            )
        else:
            print(f"{name:<16} {'FAILED':>46}")

    # 基准：等权持有
    print("-" * 64)
    print(f"{'(MVP1 基准)':<16} {'-0.5%':>10} {'-0.82':>8} {'6.4%':>10} {'34.0%':>8} {'—':>10}")

    print("\n💡 因子均为价格代理变量 (PE分位=价格位置, ROE=年涨幅)。")
    print("   接入真实基本面数据 (华泰/国信 API) 后结果会有显著差异。")

    # 保存报告
    report_path = Path("data/reports/batch_backtest_20260709.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        f.write(f"# 白泽策略族批量回测报告\n\n")
        f.write(f"**期间**: {START_DATE} → {END_DATE}  |  ")
        f.write(f"**初始资金**: ¥{INITIAL_CASH:,.0f}  |  ")
        f.write(f"**股票池**: HS300 ({len(data_map)}只)\n\n")
        f.write(f"## 汇总\n\n")
        f.write(f"| 策略 | 年化收益 | 夏普 | 最大回撤 | 胜率 | 交易次数 |\n")
        f.write(f"|------|---------|------|---------|------|--------|\n")
        for name, r, _n in results:
            if r is not None:
                f.write(
                    f"| {name} | {r.annual_return:.1%} | {r.sharpe_ratio:.2f} | "
                    f"{r.max_drawdown:.1%} | {r.win_rate:.1%} | {r.total_trades} |\n"
                )
            else:
                f.write(f"| {name} | FAILED | — | — | — | — |\n")
        f.write(f"\n> ⚠️ 因子为价格代理变量，仅供策略逻辑验证。\n")

    print(f"\n📄 报告已保存: {report_path}")


if __name__ == "__main__":
    main()
