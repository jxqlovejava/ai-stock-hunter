# -*- coding: utf-8 -*-
"""Verdict 因子计算 — 从 OHLCV 历史数据计算多维诊断评分。

复现实盘 VerdictEngine 的加权评分逻辑，跳过不可回测的部分
（Alpha Lens / 博弈论 / 思维模型 / 操纵风险 / 回调超跌）。

权重公式 (6 维, 总和 1.0):
  fundamental = (value_score + quality_score) / 2
  raw_score   = fundamental × 0.35 + valuation × 0.15 + technical × 0.15
              + macro × 0.10 + cycle × 0.10 + sector × 0.10
              + sentiment × 0.05

推荐阈值: ≥75 BUY / ≥60 ADD / ≥40 HOLD / ≥25 REDUCE / <25 SELL
"""

from __future__ import annotations

import pandas as pd

# ---- 权重 (来自 src/routing/verdict.py, 剔除 executive 后重归一化) ----

WEIGHTS = {
    "fundamental": 0.35,
    "valuation": 0.15,
    "technical": 0.15,
    "macro": 0.10,
    "cycle": 0.10,
    "sector": 0.10,
    "sentiment": 0.05,
}

REC_THRESHOLDS = [
    (75, "BUY"),
    (60, "ADD"),
    (40, "HOLD"),
    (25, "REDUCE"),
]


def score_to_rec(score: float) -> str:
    for threshold, rec in REC_THRESHOLDS:
        if score >= threshold:
            return rec
    return "SELL"


# ---- 维度计算 ----

def compute_value_score(close: pd.Series, lookback: int = 252) -> pd.Series:
    """价值评分 0-100: PE分位代理 — 价格越低越便宜=越高分。"""
    roll_max = close.rolling(lookback, min_periods=lookback // 2).max()
    roll_min = close.rolling(lookback, min_periods=lookback // 2).min()
    pct_position = (close - roll_min) / (roll_max - roll_min + 0.01)
    return ((1 - pct_position) * 100).clip(0, 100)


def compute_quality_score(close: pd.Series) -> pd.Series:
    """质量评分 0-100: ROE代理 — 年化涨跌幅映射。"""
    ret_1y = close.pct_change(252)
    return (ret_1y * 200 + 50).clip(0, 100)  # +10% → 70, 0% → 50


def compute_valuation_score(close: pd.Series) -> pd.Series:
    """估值评分 0-100: 多时间框架价格分位混合 (63d/126d/252d)。"""
    scores = []
    for window, w in [(63, 0.3), (126, 0.3), (252, 0.4)]:
        roll_max = close.rolling(window, min_periods=window // 2).max()
        roll_min = close.rolling(window, min_periods=window // 2).min()
        pct = (close - roll_min) / (roll_max - roll_min + 0.01)
        scores.append((1 - pct) * 100 * w)
    return pd.concat(scores, axis=1).sum(axis=1).clip(0, 100)


def compute_technical_score(close: pd.Series, volume: pd.Series) -> pd.Series:
    """技术面 0-100: 动量 50% + MA区域 30% + 量确认 20%。"""
    # 动量: 21d 涨跌幅
    mom21 = close.pct_change(21)
    mom_score = (mom21 * 500 + 50).clip(0, 100)  # +10% → 100, -10% → 0

    # MA 区域折扣
    ma20 = close.rolling(20).mean()
    ma_deviation = (close - ma20) / (ma20 + 0.01)
    # 严重偏离 MA20 → 风险
    ma_discount = pd.Series(1.0, index=close.index)
    ma_discount = ma_discount.where(
        ma_deviation.abs() <= 0.1, 0.8  # >10%偏离 → ×0.8
    )
    ma_discount = ma_discount.where(
        ma_deviation.abs() <= 0.2, 0.6  # >20%偏离 → ×0.6
    )

    # 量确认
    vol_ma20 = volume.rolling(20).mean()
    vol_ratio = volume / (vol_ma20 + 0.01)
    vol_score = pd.Series(0.0, index=close.index)
    vol_score = vol_score.mask(vol_ratio > 1.2, 5.0)     # 放量 +5
    vol_score = vol_score.mask(vol_ratio < 0.5, -5.0)    # 缩量 -5

    tech = mom_score * 0.5 + mom_score * ma_discount * 0.3 + (50 + vol_score) * 0.2
    return tech.clip(0, 100)


def compute_macro_score(
    csi300_close: pd.Series,
    ma_short: int = 60,
    ma_long: int = 200,
) -> pd.Series:
    """宏观评分 0-100: CSI300 趋势代理。"""
    ma60 = csi300_close.rolling(ma_short).mean()
    ma200 = csi300_close.rolling(ma_long).mean()
    ret21 = csi300_close.pct_change(21)

    above_short = csi300_close > ma60
    above_long = csi300_close > ma200
    positive_mom = ret21 > 0

    score = pd.Series(50.0, index=csi300_close.index)
    # OFFENSE: 双均线之上 + 正动量
    score = score.mask(above_short & above_long & positive_mom, 70.0)
    # NEUTRAL-UP: 短均线上 + 正动量
    score = score.mask(above_short & positive_mom, 60.0)
    # DEFENSE: 短均线下
    score = score.mask(~above_short & ~positive_mom, 30.0)
    # NEUTRAL-DOWN: 短均线下但有动量
    score = score.mask(~above_short & positive_mom, 45.0)
    # 均线上但动量负
    score = score.mask(above_short & ~positive_mom, 55.0)

    return score


def _classify_sector(code: str) -> str:
    """股票代码 → 板块分类。"""
    if code.startswith("688"):
        return "STAR"
    if code.startswith("300") or code.startswith("301"):
        return "ChiNext"
    if code.startswith("600") or code.startswith("601") or code.startswith("603"):
        return "SH_Main"
    if code.startswith("000") or code.startswith("001") or code.startswith("002"):
        return "SZ_Main"
    return "Other"


def compute_sector_scores(
    data_map: dict[str, pd.DataFrame],
    csi300_close: pd.Series,
) -> dict[str, pd.DataFrame]:
    """行业/周期评分: 板块 vs CSI300 相对强弱。

    为每个 symbol 的 DataFrame 添加 vb_cycle / vb_sector 列。
    """
    # 按板块聚合平均收益
    sector_returns: dict[str, pd.Series] = {}
    for sym, df in data_map.items():
        sec = _classify_sector(sym)
        ret63 = df["close"].pct_change(63)
        if sec not in sector_returns:
            sector_returns[sec] = ret63
        else:
            # 对齐索引取均值
            sector_returns[sec] = pd.concat(
                [sector_returns[sec], ret63], axis=1
            ).mean(axis=1)

    csi_ret63 = csi300_close.pct_change(63)

    for sym, df in data_map.items():
        sec = _classify_sector(sym)
        sec_ret = sector_returns.get(sec)
        if sec_ret is not None and csi_ret63 is not None:
            # 对齐
            aligned = pd.concat([sec_ret, csi_ret63], axis=1).ffill()
            excess = aligned.iloc[:, 0] - aligned.iloc[:, 1]
            # 周期: 超额正=扩张(高分), 超额负=收缩(低分)
            df["vb_cycle"] = (excess * 200 + 50).clip(0, 100)
            # 行业: 板块动量绝对值
            df["vb_sector"] = (aligned.iloc[:, 0] * 200 + 50).clip(0, 100)
        else:
            df["vb_cycle"] = 50.0
            df["vb_sector"] = 50.0

    return data_map


# ---- 主编排 ----

def compute_verdict_factors(
    data_map: dict[str, pd.DataFrame],
    csi300_close: pd.Series | None = None,
) -> dict[str, pd.DataFrame]:
    """为所有股票的 DataFrame 添加 vb_* 评分列。

    Args:
        data_map: {symbol: DataFrame(columns=[open,high,low,close,volume])}
        csi300_close: CSI300 收盘价序列 (index=date)。None 时用第一只股票代理。

    Returns:
        带 vb_* 列的 data_map (原地修改 + 返回)
    """
    # CSI300 代理
    if csi300_close is None:
        first_sym = next(iter(data_map.keys()))
        csi300_close = data_map[first_sym]["close"]
        print(f"  ⚠️ 无 CSI300 数据，用 {first_sym} 代理宏观基准")

    # 计算板块得分 (先做，因为需要跨股票聚合)
    data_map = compute_sector_scores(data_map, csi300_close)

    for sym, df in data_map.items():
        close = df["close"]
        volume = df.get("volume", pd.Series(1.0, index=close.index))

        vb_value = compute_value_score(close)
        vb_quality = compute_quality_score(close)
        vb_valuation = compute_valuation_score(close)
        vb_technical = compute_technical_score(close, volume)
        vb_macro = compute_macro_score(csi300_close)

        # 对齐索引 (macro/cycle/sector 可能因 rolling 有不同的 NaN 前导)
        aligned = pd.concat(
            [vb_value, vb_quality, vb_valuation, vb_technical, vb_macro,
             df["vb_cycle"], df["vb_sector"]],
            axis=1,
        ).ffill().fillna(50.0)

        df["vb_value"] = aligned.iloc[:, 0]
        df["vb_quality"] = aligned.iloc[:, 1]
        df["vb_valuation"] = aligned.iloc[:, 2]
        df["vb_technical"] = aligned.iloc[:, 3]
        df["vb_macro"] = aligned.iloc[:, 4]
        df["vb_cycle"] = aligned.iloc[:, 5]
        df["vb_sector"] = aligned.iloc[:, 6]

        # 基本面
        fundamental = (df["vb_value"] + df["vb_quality"]) / 2

        # 情绪: 量价代理
        vol_ma20 = volume.rolling(20).mean()
        vol_ratio = volume / (vol_ma20 + 0.01)
        ret5 = close.pct_change(5)
        sentiment = pd.Series(55.0, index=close.index)
        sentiment = sentiment.mask((vol_ratio > 1.5) & (ret5 < -0.03), 30.0)  # 放量跌=恐慌
        sentiment = sentiment.mask((vol_ratio > 1.5) & (ret5 > 0.03), 40.0)   # 放量涨=贪婪
        sentiment = sentiment.mask(vol_ratio < 0.5, 50.0)                     # 缩量=冷清
        df["vb_sentiment"] = sentiment

        # === 加权总分 ===
        df["vb_score"] = (
            fundamental * WEIGHTS["fundamental"]
            + df["vb_valuation"] * WEIGHTS["valuation"]
            + df["vb_technical"] * WEIGHTS["technical"]
            + df["vb_macro"] * WEIGHTS["macro"]
            + df["vb_cycle"] * WEIGHTS["cycle"]
            + df["vb_sector"] * WEIGHTS["sector"]
            + df["vb_sentiment"] * WEIGHTS["sentiment"]
        )

        # 推荐
        df["vb_rec"] = df["vb_score"].apply(score_to_rec)

    return data_map
