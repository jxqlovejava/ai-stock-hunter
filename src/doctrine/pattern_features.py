# -*- coding: utf-8 -*-
"""K 线形态特征计算 — 供军规 ctx 注入（r046-r050）。

源自《17年炒股心得》技术面纪律（技术性借鉴，非业绩背书）:
  - 换手率 > 40% 绝对阈值 → r046 换手率极端
  - MA20 乖离率硬阈值        → r047 乖离过大等回调
  - 低价股价值陷阱           → r048 低价股价值陷阱
  - 跳空三连阳出货形态       → r049 跳空三连阳出货形态
  - 高位量减价平派发         → r050 高位量减价平派发

设计:
  - 纯函数，输入 list[float] 序列，便于独立单测
  - 数据不足一律返回 None/False（防御性，与 checker 的"无数据不触发"一致）
  - 调用方从日线 df / K 线序列提取后注入 doctrine_ctx
"""

from __future__ import annotations

from typing import Optional, Sequence

__all__ = [
    "bias_vs_ma_pct",
    "turnover_rate_extreme",
    "is_low_price",
    "gap_up_three_yang",
    "high_vol_price_flat",
]


def _clean(values: Optional[Sequence]) -> list:
    """剔除 None/NaN，返回干净的 float 列表。"""
    if values is None:
        return []
    out = []
    for x in values:
        if x is None:
            continue
        try:
            f = float(x)
        except (TypeError, ValueError):
            continue
        if f != f:  # NaN
            continue
        out.append(f)
    return out


def bias_vs_ma_pct(close_series: Optional[Sequence], window: int = 20) -> Optional[float]:
    """收盘价相对 MA{window} 的乖离率(%)。

    数据不足（< window 根）返回 None。正值=股价在均线上方。
    """
    c = _clean(close_series)
    if len(c) < window:
        return None
    ma = sum(c[-window:]) / window
    if ma <= 0:
        return None
    return (c[-1] / ma - 1.0) * 100.0


def turnover_rate_extreme(turnover_rate: Optional[float], threshold: float = 40.0) -> bool:
    """单日换手率是否超过绝对阈值（%，如 40）。

    用于 r046：换手 > 40% = 主力与散户剧烈对打，胜率极低。
    """
    if turnover_rate is None:
        return False
    try:
        return float(turnover_rate) > threshold
    except (TypeError, ValueError):
        return False


def is_low_price(price: Optional[float], threshold: float = 6.0) -> bool:
    """是否低于阈值股价（如 6 元）→ 价值陷阱警示。

    A 股语境：低价≠低估，多为 ST/壳/仙股，注册制下面值退市风险。
    软标记，非硬排除（银行/大盘低价蓝筹不适用）。
    """
    if price is None:
        return False
    try:
        return float(price) < threshold
    except (TypeError, ValueError):
        return False


def gap_up_three_yang(opens: Optional[Sequence], closes: Optional[Sequence]) -> bool:
    """跳空三连阳：连续 3 日 开盘 > 昨收 且 收 > 开（阳线）。

    主力拉一波就跑的典型加速形态。三日中任一日不满足 → False。
    """
    o = _clean(opens)
    c = _clean(closes)
    if len(o) < 3 or len(c) < 4:
        return False
    for i in range(-3, 0):
        if not (o[i] > c[i - 1] and c[i] > o[i]):
            return False
    return True


def high_vol_price_flat(
    closes: Optional[Sequence],
    volumes: Optional[Sequence],
    window: int = 60,
    pos_tol: float = 0.03,
    shrink_ratio: float = 0.7,
    flat_tol: float = 2.0,
) -> bool:
    """高位量减价平 → 派发预警（r050）。

    全部满足才判定：
      - 位置高：现价距 window 日最高价回落 < pos_tol（3%）
      - 量缩：近 3 日均量 < window 日均量 * shrink_ratio（0.7）
      - 价平：近 3 日收盘变化幅度 < flat_tol（±2%）
    """
    c = _clean(closes)
    v = _clean(volumes)
    if len(c) < window or len(v) < window:
        return False
    recent = c[-window:]
    high = max(recent)
    if high <= 0:
        return False
    if (high - c[-1]) / high > pos_tol:
        return False  # 已从高位回落过多，不算"价平"
    avg_vol_win = sum(v[-window:]) / window
    if avg_vol_win <= 0:
        return False
    vol_recent = sum(v[-3:]) / 3
    if vol_recent >= avg_vol_win * shrink_ratio:
        return False  # 量未缩
    if len(c) >= 4:
        chg3 = (c[-1] / c[-4] - 1.0) * 100.0
        if abs(chg3) > flat_tol:
            return False  # 价未平
    return True
