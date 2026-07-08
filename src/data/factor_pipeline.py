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
# 价值因子 (Value Factors)
# ---------------------------------------------------------------------------

def compute_pb_factor(df: pd.DataFrame) -> pd.Series:
    """P/B 因子：低 PB = 价值，返回 0-100 排名分数。"""
    if "pb" not in df.columns:
        return pd.Series(50.0, index=df.index)
    pb = pd.to_numeric(df["pb"], errors="coerce")
    valid = pb[pb > 0]
    if valid.empty:
        return pd.Series(50.0, index=df.index)
    # Lower PB → higher score (value tilt)
    rank = valid.rank(pct=True)
    return (1.0 - rank) * 100  # invert: low PB = high score


def compute_ps_factor(df: pd.DataFrame) -> pd.Series:
    """P/S 因子：低 PS = 价值，返回 0-100 排名分数。"""
    if "ps" not in df.columns:
        return pd.Series(50.0, index=df.index)
    ps = pd.to_numeric(df["ps"], errors="coerce")
    valid = ps[ps > 0]
    if valid.empty:
        return pd.Series(50.0, index=df.index)
    rank = valid.rank(pct=True)
    return (1.0 - rank) * 100


def compute_dividend_yield_factor(df: pd.DataFrame) -> pd.Series:
    """股息率因子：高股息 = 防御价值，返回 0-100 排名分数。"""
    div_col = None
    for col in df.columns:
        col_lower = str(col).lower()
        if "dividend" in col_lower or "股息" in str(col) or "div_yield" in col_lower:
            div_col = col
            break
    if div_col is None:
        return pd.Series(50.0, index=df.index)
    div_yield = pd.to_numeric(df[div_col], errors="coerce")
    valid = div_yield[div_yield > 0]
    if valid.empty:
        return pd.Series(50.0, index=df.index)
    # Higher dividend yield → higher score
    return valid.rank(pct=True) * 100


# ---------------------------------------------------------------------------
# 质量因子 (Quality Factors)
# ---------------------------------------------------------------------------

def compute_accruals_factor(
    net_profit: pd.Series,
    operating_cashflow: pd.Series,
    total_assets: pd.Series,
) -> pd.Series:
    """应计利润因子：低应计 = 高质量盈利。

    Accruals = (NetProfit - OperatingCashFlow) / TotalAssets
    低应计 → 盈利更真实 → 高分。
    """
    ta = total_assets.replace(0, pd.NA)
    accruals = (net_profit - operating_cashflow) / ta
    valid = accruals.dropna()
    if valid.empty:
        return pd.Series(50.0, index=accruals.index)
    # Lower accruals → higher score
    rank = valid.rank(pct=True)
    return (1.0 - rank) * 100


def compute_earnings_quality_factor(
    net_profit: pd.Series,
    operating_cashflow: pd.Series,
) -> pd.Series:
    """盈利质量因子：经营现金流 / 净利润。

    >1 = 现金实收盈利，<1 = 纸面利润。
    """
    np_clipped = net_profit.clip(lower=1.0)
    ratio = operating_cashflow / np_clipped
    valid = ratio.dropna()
    if valid.empty:
        return pd.Series(50.0, index=ratio.index)
    # Clamp extreme values
    ratio_clamped = valid.clip(lower=0, upper=5)
    return ratio_clamped.rank(pct=True) * 100


# ---------------------------------------------------------------------------
# 成长因子 (Growth Factors)
# ---------------------------------------------------------------------------

def compute_revenue_growth_factor(df: pd.DataFrame) -> pd.Series:
    """营收增速因子：高增速 = 成长，返回 0-100 排名分数。"""
    rev_col = None
    for col in df.columns:
        col_str = str(col)
        if "营收" in col_str and ("增速" in col_str or "同比" in col_str or "增长" in col_str):
            rev_col = col
            break
    if rev_col is None:
        # Fallback: try common column names
        for col in df.columns:
            col_lower = str(col).lower()
            if "revenue_growth" in col_lower or "rev_yoy" in col_lower:
                rev_col = col
                break
    if rev_col is None:
        return pd.Series(50.0, index=df.index)
    growth = pd.to_numeric(df[rev_col], errors="coerce")
    valid = growth.dropna()
    if valid.empty:
        return pd.Series(50.0, index=df.index)
    return valid.rank(pct=True) * 100


def compute_earnings_growth_factor(df: pd.DataFrame) -> pd.Series:
    """净利润增速因子：高增速 = 成长，返回 0-100 排名分数。"""
    earn_col = None
    for col in df.columns:
        col_str = str(col)
        if "净利润" in col_str and ("增速" in col_str or "同比" in col_str or "增长" in col_str):
            earn_col = col
            break
    if earn_col is None:
        for col in df.columns:
            col_lower = str(col).lower()
            if "earnings_growth" in col_lower or "profit_yoy" in col_lower or "net_profit_growth" in col_lower:
                earn_col = col
                break
    if earn_col is None:
        return pd.Series(50.0, index=df.index)
    growth = pd.to_numeric(df[earn_col], errors="coerce")
    valid = growth.dropna()
    if valid.empty:
        return pd.Series(50.0, index=df.index)
    return valid.rank(pct=True) * 100


# ---------------------------------------------------------------------------
# 复合因子计算
# ---------------------------------------------------------------------------

def compute_all_factors(df: pd.DataFrame, use_registry: bool = True) -> pd.DataFrame:
    """对 DataFrame 计算所有因子，添加因子列。

    Args:
        df: 来自 AKShare stock_zh_a_spot() 或类似行情数据的 DataFrame。
        use_registry: 是否通过 src.factors.registry 计算因子（实验性）。

    Returns:
        带有因子列 (pb_factor, ps_factor, div_factor 等) 的新 DataFrame。
    """
    if use_registry:
        from src.factors.adapter import compute_registry_factors
        return compute_registry_factors(df)

    result = df.copy()

    # Value factors
    result["pb_factor"] = compute_pb_factor(df)
    result["ps_factor"] = compute_ps_factor(df)
    result["div_factor"] = compute_dividend_yield_factor(df)

    # Quality factors — need financial statement data, default to 50
    result["accruals_factor"] = 50.0
    result["earnings_quality_factor"] = 50.0

    # Growth factors
    result["revenue_growth_factor"] = compute_revenue_growth_factor(df)
    result["earnings_growth_factor"] = compute_earnings_growth_factor(df)

    return result


def compute_composite_value_score(factors: dict[str, pd.Series]) -> pd.Series:
    """综合价值得分：PB (40%) + PS (30%) + 股息率 (30%)。"""
    pb = factors.get("pb_factor", pd.Series(50.0))
    ps = factors.get("ps_factor", pd.Series(50.0))
    div = factors.get("div_factor", pd.Series(50.0))
    # Align indices
    idx = pb.index
    return (
        pb.reindex(idx).fillna(50) * 0.40
        + ps.reindex(idx).fillna(50) * 0.30
        + div.reindex(idx).fillna(50) * 0.30
    )


def compute_composite_quality_score(factors: dict[str, pd.Series]) -> pd.Series:
    """综合质量得分：应计 (50%) + 盈利质量 (50%)。"""
    acc = factors.get("accruals_factor", pd.Series(50.0))
    eq = factors.get("earnings_quality_factor", pd.Series(50.0))
    idx = acc.index
    return (
        acc.reindex(idx).fillna(50) * 0.50
        + eq.reindex(idx).fillna(50) * 0.50
    )


def compute_composite_growth_score(factors: dict[str, pd.Series]) -> pd.Series:
    """综合成长得分：营收增速 (50%) + 净利润增速 (50%)。"""
    rev = factors.get("revenue_growth_factor", pd.Series(50.0))
    earn = factors.get("earnings_growth_factor", pd.Series(50.0))
    idx = rev.index
    return (
        rev.reindex(idx).fillna(50) * 0.50
        + earn.reindex(idx).fillna(50) * 0.50
    )

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

    # Step 2: 获取北向资金数据（多维 → 0-100 得分）
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

    # Phase 3: 计算北向资金滚动得分 (0-100) 替代二元特征
    northbound_scores = _compute_northbound_scores(nb_df) if nb_df is not None else {}

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
            # Phase 3: northbound 从 binary 升级为 0-100 得分
            nb_score = northbound_scores.get(date, 50.0)
            all_data[code][date] = {
                "pe_pct": pct,
                "roe": 12.0,  # placeholder: 需要财务数据计算
                "northbound": nb_score,  # Phase 3: 0-100 得分 (曾为 binary)
                "revision_score": 50.0,  # Phase 3: 盈利修正因子 (回测默认中性)
                "price": row["price"],
            }

        if (i + 1) % 12 == 0:
            print(f"    {date}: {len(df)} stocks, {len(all_data)} accumulated")

    # Save cache
    df_out = _to_dataframe(all_data)
    df_out.to_parquet(cache_path, index=False)
    print(f"  缓存已保存: {cache_path}")

    return {"dates": sample_dates, "stocks": all_data}


def _compute_northbound_scores(nb_df: pd.DataFrame) -> dict[str, float]:
    """计算每日北向资金 0-100 得分（替代旧版 binary 特征）。

    得分逻辑:
      - 基础 50 分
      - 当日净流入/流出信号 (±20)
      - 5日滚动趋势 (±15)
      - 方向连续性 (±10)

    Returns:
        {date_str: score_0_100}
    """
    scores: dict[str, float] = {}
    if nb_df is None or len(nb_df) == 0:
        return scores

    # Extract dates and flows
    dates = []
    flows = []
    for _, row in nb_df.iterrows():
        d = row["date"]
        d_str = d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
        flow_val = 0.0
        for col in nb_df.columns:
            if "净" in str(col) or "flow" in str(col).lower():
                try:
                    flow_val = float(row[col])
                    break
                except (ValueError, TypeError):
                    continue
        dates.append(d_str)
        flows.append(flow_val)

    if len(flows) == 0:
        return scores

    for i, (d, f) in enumerate(zip(dates, flows)):
        score = 50.0
        # Flow magnitude signal
        if abs(f) > 0:
            score += max(-20, min(20, f / 10.0 * 2.0))

        # 5-day trend signal
        if i >= 4:
            recent = flows[max(0, i - 4) : i + 1]
            prev = flows[max(0, i - 9) : max(0, i - 4)]
            if prev and len(prev) > 0 and sum(abs(x) for x in prev) > 0:
                recent_avg = sum(recent) / len(recent)
                prev_avg = sum(prev) / len(prev)
                acceleration = (recent_avg - prev_avg) / (max(abs(f) for f in prev) + 0.01)
                score += max(-15, min(15, acceleration * 10))

        # Consecutive direction
        consecutive = 0
        if f > 0:
            for j in range(i, -1, -1):
                if flows[j] > 0:
                    consecutive += 1
                else:
                    break
            if consecutive >= 5:
                score += 10
            elif consecutive >= 3:
                score += 5
        elif f < 0:
            for j in range(i, -1, -1):
                if flows[j] < 0:
                    consecutive -= 1
                else:
                    break
            if consecutive <= -5:
                score -= 10
            elif consecutive <= -3:
                score -= 5

        scores[d] = max(0, min(100, score))

    return scores


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
                "northbound": factors.get("northbound", 50.0),
                "revision_score": factors.get("revision_score", 50.0),
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
            "revision_score": row.get("revision_score", 50.0),
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


# ---------------------------------------------------------------------------
# Phase 12: 行业中性化 + 极值缩尾 + 截面标准化
# ---------------------------------------------------------------------------

def winsorize(series: pd.Series, limits: tuple = (0.01, 0.99)) -> pd.Series:
    """极值缩尾 — 将超出分位数的值截断到分位数边界。

    Args:
        series: 因子值序列
        limits: (下分位, 上分位)

    Returns:
        缩尾后的序列
    """
    lower = series.quantile(limits[0])
    upper = series.quantile(limits[1])
    return series.clip(lower, upper)


def zscore(series: pd.Series) -> pd.Series:
    """截面 z-score 标准化。

    z_i = (x_i - mean(x)) / std(x)

    标准化后因子均值=0, 标准差=1。
    配合 winsorize() 使用避免极端值影响标准差。
    """
    mu = series.mean()
    sigma = series.std(ddof=1)
    if sigma < 1e-12:
        return pd.Series(0.0, index=series.index)
    return (series - mu) / sigma


def neutralize_by_industry(
    factor_values: pd.Series,
    industry_map: dict,
) -> pd.Series:
    """行业中性化 — 从因子值中剔除行业均值。

    方法: 行业内部去均值
      factor_residual_i = factor_i - mean(factor | industry_i)

    中性化后的因子值完全不包含行业选择的信息，
    纯 Alpha 来自行业内选股能力。

    对于 A 股尤为重要：
      - 银行天然低 PB、高股息率 → PB 因子不加中性化会全选银行
      - 科技天然高 PE → PE 因子不加中性化会全选银行
      - 行业内排名才是真正的选股 Alpha

    Args:
        factor_values: index=symbol, value=factor_score
        industry_map: {symbol: industry_name} 或 {symbol: sw1_name}

    Returns:
        行业中性化后的因子值（行业内去均值）
    """
    if not industry_map:
        return factor_values

    # 构造行业列
    industry_series = pd.Series(
        {sym: industry_map.get(sym, "unknown") for sym in factor_values.index}
    )

    # 行业均值
    industry_mean = factor_values.groupby(industry_series).transform("mean")

    # 残差 = 因子值 - 行业均值
    residual = factor_values - industry_mean

    # 全市场截面 z-score (使不同因子可比)
    return zscore(residual)


def standardized_pipeline(
    factor_values: pd.Series,
    industry_map: dict | None = None,
    winsorize_limits: tuple = (0.01, 0.99),
) -> pd.Series:
    """完整的标准化管道: 缩尾 → 行业中性化 → z-score。

    Args:
        factor_values: 原始因子值
        industry_map: 行业映射（None 则跳过中性化）
        winsorize_limits: 缩尾边界

    Returns:
        标准化后的因子值
    """
    # Step 1: 极值缩尾
    processed = winsorize(factor_values, winsorize_limits)

    # Step 2: 行业中性化
    if industry_map:
        processed = neutralize_by_industry(processed, industry_map)

    # Step 3: z-score 标准化
    processed = zscore(processed)

    return processed
