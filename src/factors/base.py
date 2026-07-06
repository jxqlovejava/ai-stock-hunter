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
