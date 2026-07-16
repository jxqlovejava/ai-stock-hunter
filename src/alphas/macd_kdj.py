# -*- coding: utf-8 -*-
"""MACD + KDJ 五法结合 — 来自 tweet-digest「5种常用的MACD+KDJ结合使用方法」。

规则（口播教学，nature=interpretation，不单独构成交易信号）：
  1. 双指标共振金叉 → 进场候选
  2. 双指标共振死叉 / 0轴下+KDJ死叉 → 离场候选
  3. MACD 在零轴下无拐头 + KDJ 金叉 → 勿轻易进场
  4. MACD 在零轴上无死叉/顶背离 + KDJ 金叉 → 可进场
  5. 双死叉后小幅洗盘、再双金叉 → 继续持股

置信度上限 0.5（推测/教学规则）；正式信号仍须过完整管道。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

from src.routing.signal import Direction, Signal

from .base import AlphaModel

logger = logging.getLogger(__name__)

# 教学规则：最高信心度封顶
_MAX_CONFIDENCE = 0.50
_MIN_BARS = 40  # MACD 慢线 + 信号线 + KDJ 缓冲


class MacdKdjMethod(str, Enum):
    """五法枚举。"""

    RESONANCE_GOLDEN = "M1_resonance_golden"  # 共振金叉进场
    RESONANCE_DEATH = "M2_resonance_death"  # 共振死叉离场
    BELOW_ZERO_AVOID = "M3_below_zero_avoid"  # 0轴下假反弹勿进
    ABOVE_ZERO_ENTER = "M4_above_zero_enter"  # 0轴上顺势金叉
    WASH_HOLD = "M5_wash_hold"  # 洗盘后继续持股


class MacdKdjAction(str, Enum):
    """动作标签（非强制下单）。"""

    ENTER = "ENTER"
    EXIT = "EXIT"
    AVOID_ENTRY = "AVOID_ENTRY"
    HOLD = "HOLD"
    NONE = "NONE"


@dataclass(frozen=True)
class MacdKdjBarState:
    """单日 MACD+KDJ 状态快照（不可变 DTO）。"""

    date: Optional[str]
    dif: float
    dea: float
    hist: float
    k: float
    d: float
    j: float
    macd_golden: bool
    macd_death: bool
    kdj_golden: bool
    kdj_death: bool
    macd_above_zero: bool  # DIF 与 DEA 均 > 0
    macd_below_zero: bool  # DIF 与 DEA 均 < 0
    methods: tuple[MacdKdjMethod, ...] = ()
    action: MacdKdjAction = MacdKdjAction.NONE
    confidence: float = 0.0
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class MacdKdjSeries:
    """全序列计算结果。"""

    dif: pd.Series
    dea: pd.Series
    hist: pd.Series
    k: pd.Series
    d: pd.Series
    j: pd.Series
    macd_golden: pd.Series
    macd_death: pd.Series
    kdj_golden: pd.Series
    kdj_death: pd.Series
    states: tuple[MacdKdjBarState, ...] = ()


# ---------------------------------------------------------------------------
# Indicator math
# ---------------------------------------------------------------------------


def compute_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """返回 (DIF, DEA, histogram)。histogram = (DIF-DEA)*2 通达信风格。"""
    c = close.astype(float)
    ema_fast = c.ewm(span=fast, adjust=False).mean()
    ema_slow = c.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2.0
    return dif, dea, hist


def compute_kdj(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """通达信风格 KDJ：RSV=9，K/D 为 1/3 平滑。"""
    h = high.astype(float)
    l = low.astype(float)
    c = close.astype(float)
    lowest = l.rolling(n, min_periods=1).min()
    highest = h.rolling(n, min_periods=1).max()
    denom = (highest - lowest).replace(0, np.nan)
    rsv = 100.0 * (c - lowest) / denom
    rsv = rsv.fillna(50.0)

    k_vals = np.empty(len(rsv), dtype=float)
    d_vals = np.empty(len(rsv), dtype=float)
    k_prev, d_prev = 50.0, 50.0
    alpha_k = 1.0 / m1
    alpha_d = 1.0 / m2
    for i, r in enumerate(rsv.to_numpy()):
        k_prev = (1.0 - alpha_k) * k_prev + alpha_k * float(r)
        d_prev = (1.0 - alpha_d) * d_prev + alpha_d * k_prev
        k_vals[i] = k_prev
        d_vals[i] = d_prev
    k = pd.Series(k_vals, index=close.index)
    d = pd.Series(d_vals, index=close.index)
    j = 3.0 * k - 2.0 * d
    return k, d, j


def _cross_up(a: pd.Series, b: pd.Series) -> pd.Series:
    """a 上穿 b。"""
    prev_a, prev_b = a.shift(1), b.shift(1)
    return (prev_a <= prev_b) & (a > b)


def _cross_down(a: pd.Series, b: pd.Series) -> pd.Series:
    """a 下穿 b。"""
    prev_a, prev_b = a.shift(1), b.shift(1)
    return (prev_a >= prev_b) & (a < b)


def detect_macd_top_divergence(
    close: pd.Series,
    dif: pd.Series,
    lookback: int = 20,
) -> pd.Series:
    """简易顶背离：窗口内价格创新高但 DIF 未创新高。"""
    n = len(close)
    out = np.zeros(n, dtype=bool)
    c = close.to_numpy(dtype=float)
    m = dif.to_numpy(dtype=float)
    for i in range(lookback, n):
        window_c = c[i - lookback : i + 1]
        window_m = m[i - lookback : i + 1]
        if not np.isfinite(window_c).all() or not np.isfinite(window_m).all():
            continue
        # 当前接近窗口最高价，但 DIF 明显低于窗口内 DIF 峰值
        if window_c[-1] >= np.max(window_c) * 0.998:
            peak_dif = np.max(window_m)
            if peak_dif - window_m[-1] > abs(peak_dif) * 0.15 + 1e-6:
                out[i] = True
    return pd.Series(out, index=close.index)


# ---------------------------------------------------------------------------
# Five-method classifier
# ---------------------------------------------------------------------------


def classify_bar(
    *,
    dif: float,
    dea: float,
    k: float,
    d: float,
    macd_golden: bool,
    macd_death: bool,
    kdj_golden: bool,
    kdj_death: bool,
    top_div: bool = False,
    prev_dual_death_recent: bool = False,
    small_pullback: bool = False,
) -> tuple[tuple[MacdKdjMethod, ...], MacdKdjAction, float, tuple[str, ...]]:
    """对单 bar 应用五法，返回 (methods, action, confidence, notes)。

    优先级：离场/回避 > 进场 > 持股（同 bar 可叠加 notes）。
    """
    methods: list[MacdKdjMethod] = []
    notes: list[str] = []
    action = MacdKdjAction.NONE
    conf = 0.0

    both_below = dif < 0 and dea < 0
    both_above = dif > 0 and dea > 0
    no_upturn = dif <= dea  # 未拐头向上（DIF 仍在 DEA 下或重合）

    # M2 离场 — 最高优先级风控
    if (macd_death and kdj_death) or (both_below and kdj_death):
        methods.append(MacdKdjMethod.RESONANCE_DEATH)
        notes.append("共振死叉或0轴下KDJ死叉 → 离场候选")
        action = MacdKdjAction.EXIT
        conf = max(conf, 0.48 if macd_death and kdj_death else 0.42)

    # M3 假反弹回避
    if both_below and no_upturn and kdj_golden and not macd_golden:
        methods.append(MacdKdjMethod.BELOW_ZERO_AVOID)
        notes.append("MACD双线0轴下未拐头 + KDJ金叉 → 勿轻易进场")
        if action == MacdKdjAction.NONE:
            action = MacdKdjAction.AVOID_ENTRY
        conf = max(conf, 0.45)

    # M1 共振金叉进场
    if both_below and macd_golden and kdj_golden:
        methods.append(MacdKdjMethod.RESONANCE_GOLDEN)
        notes.append("0轴下MACD+KDJ共振金叉 → 进场候选")
        if action not in (MacdKdjAction.EXIT, MacdKdjAction.AVOID_ENTRY):
            action = MacdKdjAction.ENTER
        conf = max(conf, 0.50)

    # M4 0轴上顺势
    if both_above and kdj_golden and not macd_death and not top_div:
        methods.append(MacdKdjMethod.ABOVE_ZERO_ENTER)
        notes.append("0轴上趋势 + KDJ金叉（无死叉/顶背离）→ 可进场")
        if action not in (MacdKdjAction.EXIT, MacdKdjAction.AVOID_ENTRY):
            action = MacdKdjAction.ENTER
        conf = max(conf, 0.46)

    # M5 洗盘持股
    if prev_dual_death_recent and small_pullback and macd_golden and kdj_golden:
        methods.append(MacdKdjMethod.WASH_HOLD)
        notes.append("双死叉后小幅调整再双金叉 → 继续持股")
        if action == MacdKdjAction.NONE:
            action = MacdKdjAction.HOLD
        conf = max(conf, 0.40)

    conf = min(conf, _MAX_CONFIDENCE)
    return tuple(methods), action, conf, tuple(notes)


def analyze_ohlc(
    df: pd.DataFrame,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    kdj_n: int = 9,
    wash_lookback: int = 8,
    pullback_max_pct: float = 0.08,
) -> MacdKdjSeries:
    """对 OHLC DataFrame 计算指标并逐 bar 标注五法。

    需要列：high, low, close；可选 date 索引或 date 列。
    """
    if df.empty:
        empty = pd.Series(dtype=float)
        return MacdKdjSeries(
            dif=empty, dea=empty, hist=empty, k=empty, d=empty, j=empty,
            macd_golden=empty.astype(bool), macd_death=empty.astype(bool),
            kdj_golden=empty.astype(bool), kdj_death=empty.astype(bool),
            states=(),
        )

    work = df.copy()
    for col in ("high", "low", "close"):
        if col not in work.columns:
            raise ValueError(f"missing column: {col}")

    close = work["close"].astype(float)
    high = work["high"].astype(float)
    low = work["low"].astype(float)

    dif, dea, hist = compute_macd(close, fast=fast, slow=slow, signal=signal)
    k, d, j = compute_kdj(high, low, close, n=kdj_n)
    macd_golden = _cross_up(dif, dea).fillna(False)
    macd_death = _cross_down(dif, dea).fillna(False)
    kdj_golden = _cross_up(k, d).fillna(False)
    kdj_death = _cross_down(k, d).fillna(False)
    top_div = detect_macd_top_divergence(close, dif)

    dates = work["date"] if "date" in work.columns else work.index
    states: list[MacdKdjBarState] = []

    dual_death_flags = (macd_death & kdj_death).to_numpy()
    closes = close.to_numpy(dtype=float)

    for i in range(len(work)):
        # 近期是否出现过双死叉
        lo = max(0, i - wash_lookback)
        prev_dual = bool(dual_death_flags[lo:i].any()) if i > 0 else False
        # 小幅回撤：自 lookback 内高点回撤不超过阈值
        small_pb = False
        if i > 0:
            seg = closes[lo : i + 1]
            if len(seg) >= 2 and np.isfinite(seg).all():
                peak = float(np.max(seg[:-1])) if len(seg) > 1 else float(seg[0])
                if peak > 0:
                    dd = (peak - float(seg[-1])) / peak
                    small_pb = 0.0 <= dd <= pullback_max_pct

        methods, action, conf, notes = classify_bar(
            dif=float(dif.iloc[i]),
            dea=float(dea.iloc[i]),
            k=float(k.iloc[i]),
            d=float(d.iloc[i]),
            macd_golden=bool(macd_golden.iloc[i]),
            macd_death=bool(macd_death.iloc[i]),
            kdj_golden=bool(kdj_golden.iloc[i]),
            kdj_death=bool(kdj_death.iloc[i]),
            top_div=bool(top_div.iloc[i]),
            prev_dual_death_recent=prev_dual,
            small_pullback=small_pb,
        )
        date_val = dates[i] if hasattr(dates, "__getitem__") else dates.iloc[i]
        date_str = str(date_val)[:10] if date_val is not None else None
        states.append(
            MacdKdjBarState(
                date=date_str,
                dif=float(dif.iloc[i]),
                dea=float(dea.iloc[i]),
                hist=float(hist.iloc[i]),
                k=float(k.iloc[i]),
                d=float(d.iloc[i]),
                j=float(j.iloc[i]),
                macd_golden=bool(macd_golden.iloc[i]),
                macd_death=bool(macd_death.iloc[i]),
                kdj_golden=bool(kdj_golden.iloc[i]),
                kdj_death=bool(kdj_death.iloc[i]),
                macd_above_zero=float(dif.iloc[i]) > 0 and float(dea.iloc[i]) > 0,
                macd_below_zero=float(dif.iloc[i]) < 0 and float(dea.iloc[i]) < 0,
                methods=methods,
                action=action,
                confidence=conf,
                notes=notes,
            )
        )

    return MacdKdjSeries(
        dif=dif,
        dea=dea,
        hist=hist,
        k=k,
        d=d,
        j=j,
        macd_golden=macd_golden,
        macd_death=macd_death,
        kdj_golden=kdj_golden,
        kdj_death=kdj_death,
        states=tuple(states),
    )


def latest_state(df: pd.DataFrame, **kwargs) -> Optional[MacdKdjBarState]:
    """返回最新一根 bar 的五法状态。"""
    series = analyze_ohlc(df, **kwargs)
    if not series.states:
        return None
    return series.states[-1]


# ---------------------------------------------------------------------------
# Alpha model wrapper
# ---------------------------------------------------------------------------


class MacdKdjAlphaModel(AlphaModel):
    """MACD+KDJ 五法 Alpha — 仅输出辅助 Signal，confidence ≤ 0.5。"""

    def __init__(
        self,
        symbol: str = "",
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        kdj_n: int = 9,
        confidence_cap: float = _MAX_CONFIDENCE,
    ) -> None:
        self.symbol = symbol
        self.fast = fast
        self.slow = slow
        self.signal_period = signal
        self.kdj_n = kdj_n
        self.confidence_cap = min(confidence_cap, _MAX_CONFIDENCE)
        self.minimum_data = _MIN_BARS

    def update(self, market_data: pd.DataFrame) -> list[Signal]:
        if market_data is None or market_data.empty:
            return []
        if len(market_data) < self.minimum_data:
            return []

        df = market_data
        if "close" not in df.columns:
            return []
        # 缺 high/low 时用 close 退化（KDJ 质量下降）
        if "high" not in df.columns or "low" not in df.columns:
            df = df.copy()
            df["high"] = df["close"]
            df["low"] = df["close"]

        state = latest_state(
            df,
            fast=self.fast,
            slow=self.slow,
            signal=self.signal_period,
            kdj_n=self.kdj_n,
        )
        if state is None or state.action == MacdKdjAction.NONE:
            return []

        direction = {
            MacdKdjAction.ENTER: Direction.UP,
            MacdKdjAction.EXIT: Direction.DOWN,
            MacdKdjAction.AVOID_ENTRY: Direction.FLAT,
            MacdKdjAction.HOLD: Direction.FLAT,
        }.get(state.action, Direction.FLAT)

        conf = min(state.confidence, self.confidence_cap)
        return [
            Signal(
                symbol=self.symbol,
                direction=direction,
                confidence=conf,
                source_model=self.__class__.__name__,
                created_at=datetime.now(),
                time_horizon="short",
                metadata={
                    "strategy": "macd_kdj_five_methods",
                    "action": state.action.value,
                    "methods": [m.value for m in state.methods],
                    "notes": list(state.notes),
                    "dif": state.dif,
                    "dea": state.dea,
                    "k": state.k,
                    "d": state.d,
                    "j": state.j,
                    "date": state.date,
                    "nature": "interpretation",
                    "tier": "tertiary",
                    "max_confidence_cap": self.confidence_cap,
                    "disclaimer": "教学规则辅助，不构成交易信号；须过完整管道",
                },
            )
        ]

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(symbol={self.symbol!r}, "
            f"fast={self.fast}, slow={self.slow}, signal={self.signal_period})"
        )
