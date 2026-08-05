# -*- coding: utf-8 -*-
"""Alpha 算子库。

所有算子作用于宽面板 DataFrame：index=date, columns=code。
直接借鉴 Vibe-Trading agent/src/factors/base.py，保持 NaN 传播并拒绝 inf。
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
import pandas as pd


class AlphaCompute(Protocol):
    """Alpha 计算函数协议。"""

    def __call__(self, panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
        ...


# ---------------------------------------------------------------------------
# 安全工具函数
# ---------------------------------------------------------------------------


def safe_div(a: pd.DataFrame, b: pd.DataFrame, eps: float = 1e-12) -> pd.DataFrame:
    """安全除法，避免除以 0。"""
    return a / (b + eps)


def _validate(df: pd.DataFrame, name: str = "") -> pd.DataFrame:
    """检查 inf 并拒绝。"""
    if np.isinf(df.to_numpy()).any():
        raise ValueError(f"Alpha {name} produced inf values")
    return df


# ---------------------------------------------------------------------------
# 截面算子
# ---------------------------------------------------------------------------


def rank(df: pd.DataFrame, pct: bool = True) -> pd.DataFrame:
    """逐行截面排名。"""
    return df.rank(axis=1, pct=pct)


def scale(df: pd.DataFrame, a: float = 1.0) -> pd.DataFrame:
    """逐行 L1 归一化，使 sum(abs(row)) == a。"""
    s = df.abs().sum(axis=1).replace(0, np.nan)
    return df.div(s, axis=0) * a


# ---------------------------------------------------------------------------
# 时序算子
# ---------------------------------------------------------------------------


def ts_rank(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """滚动窗口内最后值的百分位排名。"""
    return df.rolling(window=n, min_periods=1).apply(
        lambda x: x.rank(pct=True).iloc[-1], raw=False
    )


def ts_rank_value(df: pd.DataFrame, n: int, min_periods: int = 1) -> pd.DataFrame:
    """每列独立的时序 rank：当前值在自身回看窗口 n 根内的百分位（0-1，高分=偏强）。

    与截面 rank(df) 的差异：单列面板（单只股票）下 rank(axis=1) 每行唯一值恒为
    1.0，导致因子恒 100 失真；本函数按时序给当前值相对自身历史的分位，消除该失真。

    语义与 ts_rank 一致（平均秩百分位，等价于 rank(pct=True)）：窗口内最大值 → 1.0，
    最小值 → 1/k，连续平台期 → ≈0.5。这样与截面 rank 语义对齐（行内最强 → 100）。
    NaN 防御:
    - 末值为 NaN 或窗口全 NaN → 该点位 NaN（不伪装 0 分）；
    - 窗口内其它 NaN 自动剔除，只在有限值之间比较；
    - min_periods 控制最小窗口（默认 1，允许冷启动逐 bar 积累）。
    """
    def _avg_rank_pct_of_last(x: np.ndarray) -> float:
        last = x[-1]
        if not np.isfinite(last):
            return np.nan
        valid = x[np.isfinite(x)]
        k = valid.shape[0]
        if k == 0:
            return np.nan
        below = int((valid < last).sum())
        equal = int((valid == last).sum())
        # 平均秩: below 个严格小于 + 并列组平均秩 (below + (1+equal)/2)，再除以 k
        return float((below + (1.0 + equal) / 2.0) / k)

    return df.rolling(window=n, min_periods=min_periods).apply(
        _avg_rank_pct_of_last, raw=True
    )


def cross_or_ts_rank(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """面板 rank 自动路由：多列走截面 rank，单列走时序 rank，避免恒 100 失真。

    截面 rank(axis=1) 在单列面板（单只股票）下每行唯一值 rank=1.0 → 因子恒 100，
    推高趋势/反转/均线等维度。当列数 <= 1 时回退到 ts_rank_value（当前值相对自身
    n 根历史的分位）。输出语义与 rank(df) 一致（0-1，高分=强），多列行为完全不变
    （向后兼容：只新增 ts_rank 分支，不改截面 rank 默认行为）。
    """
    if df.shape[1] <= 1:
        return ts_rank_value(df, n)
    return rank(df)


def ts_corr(x: pd.DataFrame, y: pd.DataFrame, n: int) -> pd.DataFrame:
    """滚动 Pearson 相关。"""
    return x.rolling(window=n, min_periods=max(2, n // 2)).corr(y)


def ts_cov(x: pd.DataFrame, y: pd.DataFrame, n: int) -> pd.DataFrame:
    """滚动协方差。"""
    return x.rolling(window=n, min_periods=max(2, n // 2)).cov(y)


def ts_mean(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.rolling(window=n, min_periods=1).mean()


def ts_std(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.rolling(window=n, min_periods=2).std()


def ts_max(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.rolling(window=n, min_periods=1).max()


def ts_min(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.rolling(window=n, min_periods=1).min()


def ts_argmax(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.rolling(window=n, min_periods=1).apply(np.argmax, raw=True)


def ts_argmin(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.rolling(window=n, min_periods=1).apply(np.argmin, raw=True)


def delta(df: pd.DataFrame, d: int) -> pd.DataFrame:
    """d 期差分，d >= 1。"""
    return df.diff(periods=d)


def decay_linear(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """线性衰减加权滚动平均。"""
    weights = np.arange(1, n + 1)
    weights = weights / weights.sum()
    return df.rolling(window=n, min_periods=1).apply(
        lambda x: np.dot(x[-len(weights):], weights[-len(x):]), raw=True
    )


def signed_power(df: pd.DataFrame, p: float) -> pd.DataFrame:
    return np.sign(df) * (np.abs(df) ** p)


# ---------------------------------------------------------------------------
# 市场感知算子
# ---------------------------------------------------------------------------


def vwap(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """成交量加权平均价。"""
    close = panel.get("close")
    volume = panel.get("volume")
    if close is None or volume is None:
        raise ValueError("vwap requires 'close' and 'volume'")
    typical = panel.get("typical") or (panel["high"] + panel["low"] + panel["close"]) / 3.0
    return (typical * volume).rolling(window=1, min_periods=1).sum() / volume.rolling(
        window=1, min_periods=1
    ).sum()
