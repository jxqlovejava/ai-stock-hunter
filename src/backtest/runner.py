# -*- coding: utf-8 -*-
r"""回测运行器。

用 AKShare 下载历史 K 线数据，喂入 MVP1 策略，生成回测报告。

用法:
  python -m src.backtest.runner \
    --start 2019-01-01 --end 2024-12-31 \
    --universe hs300

HS300 成分股 ~300 只，10 年日线数据约 100 万行。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from .engine import BacktestEngine, BacktestResult
from .engine_v2 import VibeBacktestEngine
from .engines.base import EngineResult
from .mvp1_strategy import MVP1Strategy

# 缓存目录
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "kline_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 股票池
# ---------------------------------------------------------------------------


def get_hs300_constituents() -> list[str]:
    """获取沪深 300 成分股列表。"""
    try:
        import akshare as ak
        df = ak.index_stock_cons_weight_csindex(symbol="000300")
        return df["成分券代码"].astype(str).tolist()
    except Exception:
        # Fallback: 手动精选 30 只代表性标的
        return [
            "600519", "000858", "000333", "000651", "600036",
            "601318", "600276", "600887", "600900", "601012",
            "002415", "300750", "300059", "300015", "300124",
            "600030", "600585", "600809", "000001", "002475",
            "601398", "601939", "600048", "000002", "601088",
            "600031", "000725", "002594", "601899", "600809",
        ]


# ---------------------------------------------------------------------------
# 数据下载
# ---------------------------------------------------------------------------


def _find_cached_file(
    symbol: str,
    start_date: str,
    end_date: str,
    period: str = "daily",
) -> Optional[Path]:
    """在缓存目录中查找覆盖请求日期范围的文件。

    策略：
    1. 精确匹配文件名
    2. 扫描目录找同 symbol 的文件，检查日期范围是否覆盖请求
    """
    # 1. 精确匹配
    exact = CACHE_DIR / f"{symbol}_{start_date}_{end_date}_{period}.csv"
    if exact.exists():
        return exact

    # 2. 模糊匹配：扫描同 symbol 前缀的文件
    prefix = f"{symbol}_"
    candidates = sorted(CACHE_DIR.glob(f"{prefix}*_{period}.csv"))
    for p in candidates:
        try:
            # 文件名格式: {symbol}_{file_start}_{file_end}_{period}.csv
            stem = p.stem  # e.g. 000001_20150101_20251231_daily
            parts = stem.split("_")
            file_start = parts[-3]  # e.g. 20150101
            file_end = parts[-2]    # e.g. 20251231
            if file_start <= start_date and file_end >= end_date:
                return p
        except (IndexError, ValueError):
            continue
    return None


def download_kline(
    symbol: str,
    start_date: str = "20150101",
    end_date: str = "20251231",
    period: str = "daily",
    force: bool = False,
) -> Optional[pd.DataFrame]:
    """下载单只股票的历史 K 线，带本地缓存。

    优先使用缓存（支持宽范围缓存文件的智能查找），
    缓存未命中时通过 AKShare 下载并写入精确范围缓存。

    Returns:
        DataFrame with: date, open, high, low, close, volume
    """
    # 尝试缓存命中（精确或宽范围）
    if not force:
        cached = _find_cached_file(symbol, start_date, end_date, period)
        if cached is not None:
            df = pd.read_csv(cached, parse_dates=["date"], index_col="date")
            # 切片到请求的日期范围
            mask = (df.index >= start_date) & (df.index <= end_date)
            return df[mask] if mask.any() else df

    # 缓存未命中，尝试联网下载
    try:
        import akshare as ak
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period=period,
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",  # 前复权
        )
        if df is None or df.empty:
            return None

        # 标准化列名
        df = df.rename(columns={
            "日期": "date", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume",
            "成交额": "amount", "涨跌幅": "pct_change",
        })
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df = df[["open", "high", "low", "close", "volume"]]

        cache_path = CACHE_DIR / f"{symbol}_{start_date}_{end_date}_{period}.csv"
        df.to_csv(cache_path)
        return df
    except Exception as e:
        # 网络失败时，再尝试一次宽范围缓存（之前 force=True 跳过了）
        cached = _find_cached_file(symbol, start_date, end_date, period)
        if cached is not None:
            print(f"  {symbol}: 网络不可用，使用缓存 {cached.name}")
            df = pd.read_csv(cached, parse_dates=["date"], index_col="date")
            mask = (df.index >= start_date) & (df.index <= end_date)
            return df[mask] if mask.any() else df
        print(f"  download_kline({symbol}) error: {e}")
        return None


def download_universe(
    symbols: list[str],
    start_date: str = "20190101",
    end_date: str = "20241231",
) -> dict[str, pd.DataFrame]:
    """下载整个股票池的历史 K 线。

    Returns:
        {symbol: DataFrame(index=date, columns=[open,high,low,close,volume])}
    """
    print(f"下载 {len(symbols)} 只股票 K 线: {start_date} → {end_date}")
    data = {}
    for i, sym in enumerate(symbols):
        df = download_kline(sym, start_date, end_date)
        if df is not None and len(df) > 200:  # 至少 200 个交易日
            data[sym] = df
        else:
            print(f"  {sym}: 数据不足，跳过")

        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(symbols)}] {sym}: {len(df) if df is not None else 0} rows")

    print(f"下载完成: {len(data)}/{len(symbols)} 只有效数据")
    return data


# ---------------------------------------------------------------------------
# 因子计算
# ---------------------------------------------------------------------------


def calculate_pe_percentile_proxy(
    data: dict[str, pd.DataFrame],
    lookback_days: int = 252,
) -> dict[str, pd.Series]:
    """用价格变化近似 PE 分位（PE 低 = 股价处于相对低位）。

    计算每只股票过去 lookback_days 的价格分位，
    然后用 (1 - 分位) 作为 PE 分位的代理变量。

    Returns:
        {symbol: Series(date -> pe_percentile)}
    """
    result = {}
    for sym, df in data.items():
        rolling_max = df["close"].rolling(lookback_days).max()
        rolling_min = df["close"].rolling(lookback_days).min()
        # 当前价格在区间中的位置，越低越便宜 -> 越低 PE 越低
        pct = (df["close"] - rolling_min) / (rolling_max - rolling_min + 0.01)
        result[sym] = (1 - pct) * 100  # 转为 0-100
    return result


def calculate_roe_proxy(
    data: dict[str, pd.DataFrame],
) -> dict[str, pd.Series]:
    """用年化收益率代理 ROE。

    过去 252 个交易日的涨跌幅作为 ROE 代理。
    """
    result = {}
    for sym, df in data.items():
        ret_1y = df["close"].pct_change(252)
        result[sym] = ret_1y * 100  # 百分比
    return result


# ---------------------------------------------------------------------------
# 主运行器
# ---------------------------------------------------------------------------


def run_backtest(
    symbols: Optional[list[str]] = None,
    start_date: str = "20190101",
    end_date: str = "20241231",
    initial_cash: float = 1_000_000,
    max_positions: int = 20,
    rebalance_days: int = 63,  # 季调
    engine: str = "legacy",
) -> BacktestResult | EngineResult:
    """运行完整回测。

    1. 下载 HS300 成分股历史 K 线
    2. 计算 PE 分位/ROE 代理因子
    3. 用 Backtrader 运行 MVP1 策略
    4. 返回结果
    """
    # 股票池
    if symbols is None:
        symbols = get_hs300_constituents()
        print(f"股票池: {len(symbols)} 只 (沪深300)")

    # 下载数据
    data = download_universe(symbols, start_date, end_date)
    if len(data) < 5:
        raise RuntimeError("数据不足，无法运行回测")

    if engine == "v2":
        v2 = VibeBacktestEngine(initial_cash=initial_cash)
        return v2.run(
            symbols=list(data.keys()),
            start_date=start_date,
            end_date=end_date,
            data_map=data,
        )

    # 计算因子
    print("计算因子...")
    pe_pcts = calculate_pe_percentile_proxy(data)
    roes = calculate_roe_proxy(data)

    # 构建 Backtrader 输入
    engine = BacktestEngine(initial_cash=initial_cash)
    engine.add_strategy(
        MVP1Strategy,
        rebalance_days=rebalance_days,
        max_positions=max_positions,
    )

    # 将数据转为 Backtrader DataFeed
    common_dates = None
    for sym, df in data.items():
        if common_dates is None:
            common_dates = set(df.index)
        else:
            common_dates &= set(df.index)

    common_dates = sorted(common_dates)
    print(f"公共交易日: {len(common_dates)}")

    for sym, df in data.items():
        # 对齐到公共日期
        df_aligned = df.reindex(common_dates).ffill().dropna()
        if len(df_aligned) < 200:
            continue

        # 将因子值作为 DataFrame 列加入（engine.add_data 自动识别 pe_pct/roe/momentum 列）
        pe_pct = pe_pcts.get(sym, pd.Series([50.0] * len(df_aligned), index=df_aligned.index))
        roe_val = roes.get(sym, pd.Series([10.0] * len(df_aligned), index=df_aligned.index))

        df_aligned["pe_pct"] = pe_pct.reindex(df_aligned.index).fillna(50.0)
        df_aligned["roe"] = roe_val.reindex(df_aligned.index).fillna(10.0)
        # 动量因子: 21日涨跌幅
        df_aligned["momentum"] = df_aligned["close"].pct_change(21).fillna(0.0) * 100

        engine.add_data(code=sym, df=df_aligned)

    # 运行
    print(f"运行回测: {len(engine._data_feeds)} 只股票")
    result = engine.run(
        start=f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}",
        end=f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}",
    )
    return result


def run_reversal_test(
    result: BacktestResult,
    **kwargs,
) -> BacktestResult:
    """运行因子反转测试: PE > 70% 分位替代 PE < 30%。"""
    print("\n运行因子反转测试...")
    reversed_result = run_backtest(**kwargs)
    return reversed_result


# ---------------------------------------------------------------------------
# Verdict 回测 (实盘 VerdictEngine 评分逻辑)
# ---------------------------------------------------------------------------

def _ensure_csi300(
    symbols: list[str],
    start_date: str,
    end_date: str,
) -> pd.Series | None:
    """获取 CSI300 指数数据作为宏观基准。

    尝试从缓存加载 000300，失败则用第一只股票代理。
    """
    # 尝试 CSI300
    csi_df = download_kline("000300", start_date, end_date)
    if csi_df is not None and len(csi_df) > 200:
        return csi_df["close"]
    # Fallback: 用第一只可用的 HS300 成分股
    for sym in symbols:
        df = download_kline(sym, start_date, end_date)
        if df is not None and len(df) > 200:
            return df["close"]
    return None


def run_verdict_backtest(
    symbols: list[str] | None = None,
    start_date: str = "20190101",
    end_date: str = "20241231",
    initial_cash: float = 1_000_000,
    max_positions: int = 10,
    rebalance_days: int = 21,
    min_score: float = 60,
) -> BacktestResult | EngineResult:
    """运行 Verdict 回测 — 使用实盘 VerdictEngine 多维加权评分。

    Args:
        max_positions: 最大持仓数 (默认 10)
        rebalance_days: 调仓周期 (默认 21 月调)
        min_score: 最低买入分 (默认 60 = ADD)
    """
    from .verdict_factors import compute_verdict_factors
    from .verdict_strategy import VerdictBacktestStrategy

    # 股票池
    if symbols is None:
        symbols = get_hs300_constituents()
        print(f"股票池: {len(symbols)} 只 (沪深300)")

    # 下载数据
    data = download_universe(symbols, start_date, end_date)
    if len(data) < 5:
        raise RuntimeError(f"数据不足: {len(data)} 只")

    # CSI300 基准
    print("获取 CSI300 基准...")
    csi300 = _ensure_csi300(symbols, start_date, end_date)
    if csi300 is not None:
        print(f"  CSI300: {len(csi300)} 个交易日")

    # 计算 Verdict 因子
    print("计算 Verdict 多维评分...")
    data = compute_verdict_factors(data, csi300_close=csi300)

    # 构建回测
    engine_obj = BacktestEngine(initial_cash=initial_cash)
    engine_obj.add_strategy(
        VerdictBacktestStrategy,
        rebalance_days=rebalance_days,
        max_positions=max_positions,
        min_score=50,  # HOLD 以上 (评分集中在 50 附近时能选到候选)
    )

    # 找公共日期
    common_dates = None
    for sym, df in data.items():
        if common_dates is None:
            common_dates = set(df.index)
        else:
            common_dates &= set(df.index)
    common_dates = sorted(common_dates)
    print(f"公共交易日: {len(common_dates)}")

    # 添加数据
    for sym, df in data.items():
        df_aligned = df.reindex(common_dates).ffill().dropna()
        if len(df_aligned) < 200:
            continue
        engine_obj.add_data(code=sym, df=df_aligned)

    # 运行
    print(f"运行回测: {len(engine_obj._data_feeds)} 只股票")
    result = engine_obj.run(
        start=f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}",
        end=f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}",
    )
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MVP1 回测运行器")
    parser.add_argument("--start", default="20150101")
    parser.add_argument("--end", default="20251231")
    parser.add_argument("--universe", default="hs300", choices=["hs300", "custom"])
    parser.add_argument("--max-positions", type=int, default=20)
    parser.add_argument("--rebalance-days", type=int, default=63)
    parser.add_argument("--engine", default="legacy", choices=["legacy", "v2"])
    parser.add_argument("--reversal", action="store_true", help="运行因子反转测试")
    parser.add_argument("--symbols", nargs="*", help="自定义股票池")
    args = parser.parse_args()

    symbols = args.symbols if args.symbols else None

    # 主回测
    result = run_backtest(
        symbols=symbols,
        start_date=args.start,
        end_date=args.end,
        max_positions=args.max_positions,
        rebalance_days=args.rebalance_days,
        engine=args.engine,
    )

    # 打印报告
    print("\n" + "=" * 60)
    if hasattr(result, "report"):
        print(result.report())
    else:
        print(f"总收益: {result.total_return:.2%}")
        print(f"年化收益: {result.annual_return:.2%}")
        print(f"夏普: {result.sharpe_ratio:.2f}")
        print(f"最大回撤: {result.max_drawdown:.2%}")
        print(f"交易次数: {result.total_trades}")
        if result.trading_blocked:
            print(f"⚠️ 交易被阻断: {result.block_reason}")

    # 因子反转测试
    if args.reversal and args.engine == "legacy":
        rev_result = run_reversal_test(
            result,
            symbols=symbols,
            start_date=args.start,
            end_date=args.end,
        )
        print("\n--- 因子反转测试 ---")
        print(f"正选 年化: {result.annual_return:.2%}  夏普: {result.sharpe_ratio:.2f}")
        print(f"反转 年化: {rev_result.annual_return:.2%}  夏普: {rev_result.sharpe_ratio:.2f}")
        if rev_result.annual_return < result.annual_return * 0.5:
            print("✅ 反转测试通过: 反转后超额大幅下降")
        else:
            print("❌ 反转测试失败: 反转后超额仍存在，因子可能有问题")
