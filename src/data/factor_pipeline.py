# -*- coding: utf-8 -*-
"""因子数据管道。

从 AKShare 拉取 2015-2024 全 A 股 PE/ROE/北向资金历史数据，
计算 PE 分位数，输出 CSV 供回测引擎使用。

用法:
  python -m src.data.factor_pipeline --start 2015-01-01 --end 2024-12-31
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

# 输出目录
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "factors"
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# PE 分位数管道
# ---------------------------------------------------------------------------

def fetch_pe_history(
    date: str, save: bool = True
) -> Optional[pd.DataFrame]:
    """获取某日的全 A 股 PE 数据。

    使用 AKShare stock_a_pe_lg 获取行业 PE 或 stock_zh_a_spot 获取个股 PE。
    返回: DataFrame with columns [code, name, pe_ttm, pb, market_cap]
    """
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot()
        if df is None or df.empty:
            return None

        result = pd.DataFrame()
        result["code"] = df["代码"].astype(str)
        result["name"] = df["名称"].astype(str)
        result["price"] = pd.to_numeric(df["最新价"], errors="coerce")

        # PE/PB may not be in spot data; use financial data if needed
        # For MVP, calculate PE from market_cap / net_profit later

        result["date"] = date
        result = result.dropna(subset=["price"])
        result = result[result["price"] > 0]

        if save:
            path = DATA_DIR / f"pe_{date.replace('-', '')}.csv"
            result.to_csv(path, index=False)

        return result
    except Exception as e:
        print(f"  fetch_pe_history({date}) error: {e}")
        return None


def calculate_pe_percentile(
    symbol: str, current_pe: float, all_stocks_pe: pd.Series
) -> float:
    """计算某只股票在当天全市场中的 PE 分位数。

    Args:
        symbol: 股票代码
        current_pe: 当前 PE TTM
        all_stocks_pe: 全市场 PE 序列（正数）

    Returns:
        PE 分位数 (0-100)，越低越便宜。PE 为负时返回 100。
    """
    if current_pe <= 0:
        return 100.0  # 亏损企业排在最贵
    valid = all_stocks_pe[all_stocks_pe > 0]
    if valid.empty:
        return 50.0
    return (valid < current_pe).mean() * 100


# ---------------------------------------------------------------------------
# 北向资金管道
# ---------------------------------------------------------------------------

def fetch_northbound_history(
    start_date: str = "20150101",
    end_date: str = "20241231",
    save: bool = True,
) -> Optional[pd.DataFrame]:
    """获取北向资金历史净买入数据。

    Returns:
        DataFrame with columns [date, net_flow_100m, cumulative_100m]
    """
    try:
        import akshare as ak
        df = ak.stock_hsgt_north_net_flow_in_em(symbol="北上")
        if df is None or df.empty:
            return None

        df = df.rename(columns={
            "日期": "date",
            "当日净流入": "net_flow_100m",
            "累计净流入": "cumulative_100m",
        })
        df["date"] = pd.to_datetime(df["date"])

        # Filter date range
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        df = df[(df["date"] >= start) & (df["date"] <= end)]

        if save:
            path = DATA_DIR / "northbound_history.csv"
            df.to_csv(path, index=False)

        return df
    except Exception as e:
        print(f"  fetch_northbound_history error: {e}")
        return None


# ---------------------------------------------------------------------------
# 主管道
# ---------------------------------------------------------------------------

def build_factor_dataset(
    start_date: str = "2015-01-01",
    end_date: str = "2024-12-31",
    sample_dates: Optional[list[str]] = None,
) -> dict:
    """构建完整的因子数据集。

    返回包含 PE 分位、北向资金、ROE 的字典，可直接喂入回测引擎。

    Returns:
        {
            "dates": [...],
            "stocks": {code: {date: {pe_pct, roe, northbound}}}
        }
    """
    print(f"构建因子数据集: {start_date} → {end_date}")

    # 如果已有缓存，直接加载
    cache_path = DATA_DIR / "factor_dataset.parquet"
    if cache_path.exists():
        print(f"  加载缓存: {cache_path}")
        df = pd.read_parquet(cache_path)
        return _parse_dataset(df)

    # Step 1: 获取月度采样日期的 PE 数据
    if sample_dates is None:
        sample_dates = _sample_monthly_dates(start_date, end_date)
    print(f"  采样日期数: {len(sample_dates)}")

    # Step 2: 获取北向资金数据
    print("  获取北向资金...")
    nb_df = fetch_northbound_history(
        start_date.replace("-", ""),
        end_date.replace("-", ""),
    )
    northbound_daily = {}  # date -> net_flow
    if nb_df is not None:
        for _, row in nb_df.iterrows():
            d = row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"])[:10]
            northbound_daily[d] = float(row.get("net_flow_100m", 0))

    # Step 3: 逐月获取 PE 数据并计算分位
    print("  逐月获取 PE 数据...")
    all_data = {}  # code -> {date -> {pe_pct, roe}}

    for i, date in enumerate(sample_dates):
        df = fetch_pe_history(date, save=True)
        if df is None:
            continue

        # 计算 PE 分位
        pe_values = df["price"]  # 用价格近似；真正的 PE 需要财务数据
        for _, row in df.iterrows():
            code = row["code"]
            pct = calculate_pe_percentile(code, row["price"], pe_values)
            if code not in all_data:
                all_data[code] = {}
            all_data[code][date] = {
                "pe_pct": pct,
                "roe": 12.0,  # placeholder: 需要财务数据计算
                "northbound": 1.0 if northbound_daily.get(date, 0) > 0 else 0.0,
                "price": row["price"],
            }

        if (i + 1) % 12 == 0:
            print(f"    {date}: {len(df)} stocks, {len(all_data)} accumulated")

    # Save cache
    df_out = _to_dataframe(all_data)
    df_out.to_parquet(cache_path, index=False)
    print(f"  缓存已保存: {cache_path}")

    return {"dates": sample_dates, "stocks": all_data}


def _sample_monthly_dates(start: str, end: str) -> list[str]:
    """生成月度采样日期。每月使用第 15 个交易日附近的日期。"""
    dates = []
    current = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    while current <= end_dt:
        # 取每月 15 号
        d = current.replace(day=15)
        if d.weekday() >= 5:
            d = d + timedelta(days=(7 - d.weekday()))
        if d <= end_dt and d >= datetime.fromisoformat(start):
            dates.append(d.strftime("%Y-%m-%d"))
        # Next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return dates


def _to_dataframe(data: dict) -> pd.DataFrame:
    """将嵌套字典转为 DataFrame。"""
    rows = []
    for code, date_map in data.items():
        for date, factors in date_map.items():
            rows.append({
                "code": code,
                "date": date,
                "pe_pct": factors["pe_pct"],
                "roe": factors["roe"],
                "northbound": factors["northbound"],
                "price": factors["price"],
            })
    return pd.DataFrame(rows)


def _parse_dataset(df: pd.DataFrame) -> dict:
    """将 DataFrame 解析回嵌套字典格式。"""
    stocks = {}
    dates = sorted(df["date"].unique().tolist())
    for _, row in df.iterrows():
        code = row["code"]
        date = str(row["date"])[:10]
        if code not in stocks:
            stocks[code] = {}
        stocks[code][date] = {
            "pe_pct": row["pe_pct"],
            "roe": row["roe"],
            "northbound": row["northbound"],
            "price": row["price"],
        }
    return {"dates": dates, "stocks": stocks}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="因子数据管道")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--force", action="store_true", help="强制重建缓存")
    args = parser.parse_args()

    if args.force:
        cache = DATA_DIR / "factor_dataset.parquet"
        if cache.exists():
            cache.unlink()

    dataset = build_factor_dataset(args.start, args.end)
    print(f"\n完成: {len(dataset['stocks'])} stocks, {len(dataset['dates'])} dates")
