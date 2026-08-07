# -*- coding: utf-8 -*-
"""VWAP 成本带分析 — 现价 vs 真实持仓成本 + 反弹/回调真假判定。

把 VWAP（成交量加权平均价）作为"市场真实持仓成本"的刻度尺：

1. compute_vwap_band — 计算 vwap20/vwap60 + 现价偏离度 + 成本带区间
2. detect_vwap_events — 站上/跌破 + 真突破/诱多 四类信号
3. band_vs_ma       — VWAP 与 MA 构成成本带，带宽收窄=变盘提示

数据无 amount 字段时以 typical price (H+L+C)/3 × volume 近似（同 arxiv_factors）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 信号 DTO — 镜像 t0_decision.T0Signal 结构
# ---------------------------------------------------------------------------


@dataclass
class VwapSignal:
    """单个 VWAP 信号。"""

    direction: str        # "bull" | "bear"
    weight: int           # 影响分（正=加分，负=减分）
    category: str         # "vwap_band"
    description: str
    price: float = 0.0    # 关联价位（VWAP / 前高 / 支撑）
    zone: str = ""        # 观察区间提示


@dataclass
class VwapBandResult:
    """VWAP 成本带分析结果。"""

    symbol: str = ""
    name: str = ""

    # 成本带核心数值
    vwap20: float = 0.0
    vwap60: float = 0.0
    price: float = 0.0
    price_vs_vwap20: float = 0.0       # 现价对 vwap20 偏离 %（>0 高于成本）
    price_vs_vwap60: float = 0.0

    # 成本带区间（VWAP20 与 MA 的上下轨）
    band_high: float = 0.0
    band_low: float = 0.0
    band_ma20: float = 0.0
    band_ma5: float = 0.0
    band_range: float = 0.0            # 成本带宽度 %
    band_position: str = ""            # "上轨上方" / "带内" / "下轨下方"

    # 位置与信号
    position_vs_vwap: str = ""         # "VWAP上方" / "VWAP下方" / "贴近VWAP"
    signals: list[VwapSignal] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "vwap20": round(self.vwap20, 2),
            "vwap60": round(self.vwap60, 2),
            "price": self.price,
            "price_vs_vwap20": round(self.price_vs_vwap20, 2),
            "price_vs_vwap60": round(self.price_vs_vwap60, 2),
            "band_high": round(self.band_high, 2),
            "band_low": round(self.band_low, 2),
            "band_ma20": round(self.band_ma20, 2),
            "band_ma5": round(self.band_ma5, 2),
            "band_range": round(self.band_range, 2),
            "band_position": self.band_position,
            "position_vs_vwap": self.position_vs_vwap,
            "signals": [
                {"direction": s.direction, "weight": s.weight,
                 "category": s.category, "description": s.description,
                 "price": s.price, "zone": s.zone}
                for s in self.signals
            ],
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# 核心计算
# ---------------------------------------------------------------------------


def _typical_price(df: pd.DataFrame) -> pd.Series:
    """typical price = (H+L+C)/3，VWAP 近似用。"""
    return (df["high"] + df["low"] + df["close"]) / 3.0


def compute_vwap_band(
    df: pd.DataFrame,
    price: float = 0.0,
    *,
    symbol: str = "",
    name: str = "",
) -> VwapBandResult:
    """计算 VWAP 成本带。

    Args:
        df: 日线 DataFrame，需含 open/high/low/close/volume（或中文列名）
        price: 现价；为 0 时用最后一根收盘价
        symbol/name: 标的标识
    """
    if df is None or df.empty:
        return VwapBandResult(symbol=symbol, name=name,
                              summary="[DATA_GAP] 无日线数据")

    # 列名标准化（中文 → 英文）
    col_map = {
        "开盘": "open", "最高": "high", "最低": "low",
        "收盘": "close", "成交量": "volume", "vol": "volume",
    }
    df = df.rename(columns={c: col_map[c] for c in df.columns if c in col_map})
    needed = {"high", "low", "close", "volume"}
    if not needed.issubset(df.columns):
        logger.debug("vwap_band: 缺列 %s", needed - set(df.columns))
        return VwapBandResult(symbol=symbol, name=name,
                              summary="[DATA_GAP] K线列不完整")

    close = df["close"].astype(float)
    volume = df["volume"].astype(float)
    typical = _typical_price(df)

    # 滚动 VWAP（typical × volume 加权）
    amt20 = (typical * volume).rolling(20, min_periods=1).sum()
    vol20 = volume.rolling(20, min_periods=1).sum()
    vwap20 = (amt20 / vol20.replace(0, np.nan)).iloc[-1]

    vwap60 = 0.0
    if len(df) >= 60:
        amt60 = (typical * volume).rolling(60, min_periods=1).sum()
        vol60 = volume.rolling(60, min_periods=1).sum()
        vwap60 = (amt60 / vol60.replace(0, np.nan)).iloc[-1]

    # MA
    ma5 = float(close.rolling(5, min_periods=1).mean().iloc[-1])
    ma20 = float(close.rolling(20, min_periods=1).mean().iloc[-1])

    curr = float(price) if price > 0 else float(close.iloc[-1])

    result = VwapBandResult(symbol=symbol, name=name)
    result.vwap20 = float(vwap20) if np.isfinite(vwap20) else 0.0
    result.vwap60 = float(vwap60) if np.isfinite(vwap60) else 0.0
    result.price = curr
    result.band_ma5 = ma5
    result.band_ma20 = ma20

    # 偏离度
    if result.vwap20 > 0:
        result.price_vs_vwap20 = (curr / result.vwap20 - 1) * 100
    if result.vwap60 > 0:
        result.price_vs_vwap60 = (curr / result.vwap60 - 1) * 100

    # 成本带：上轨 = max(vwap20, ma20)，下轨 = min(vwap20, ma20)
    active = [v for v in (result.vwap20, ma20) if v > 0]
    if active:
        result.band_high = max(active)
        result.band_low = min(active)
        mid = (result.band_high + result.band_low) / 2
        result.band_range = ((result.band_high - result.band_low) / mid * 100) if mid > 0 else 0.0
        if curr > result.band_high:
            result.band_position = "上轨上方"
        elif curr < result.band_low:
            result.band_position = "下轨下方"
        else:
            result.band_position = "带内"

    # 现价 vs VWAP 位置
    if result.vwap20 > 0:
        if curr > result.vwap20 * 1.03:
            result.position_vs_vwap = "VWAP上方"
        elif curr < result.vwap20 * 0.97:
            result.position_vs_vwap = "VWAP下方"
        else:
            result.position_vs_vwap = "贴近VWAP"

    return result


def detect_vwap_events(df: pd.DataFrame, price: float = 0.0) -> list[VwapSignal]:
    """检测 VWAP 四类事件：真突破 / 诱多 / 站上 / 跌破。

    判定逻辑（利用点 3 — 判断反弹/回调真假）：
    - 价格从下方放量站上 VWAP → 真突破（大资金愿意在此接货）
    - VWAP 上方滞涨 + 缩量 → 诱多（上涨动力不足，警惕诱多）
    - 价格从上方跌破 VWAP → 跌破（成本线下移，偏弱）
    - 价涨量缩且低于 VWAP → 弱反弹（无有效承接）
    """
    if df is None or df.empty or len(df) < 20:
        return []

    col_map = {
        "开盘": "open", "最高": "high", "最低": "low",
        "收盘": "close", "成交量": "volume", "vol": "volume",
    }
    df = df.rename(columns={c: col_map[c] for c in df.columns if c in col_map})
    if not {"high", "low", "close", "volume"}.issubset(df.columns):
        return []

    close = df["close"].astype(float)
    volume = df["volume"].astype(float)
    typical = _typical_price(df)
    amt20 = (typical * volume).rolling(20, min_periods=1).sum()
    vol20 = volume.rolling(20, min_periods=1).sum()
    vwap20_series = amt20 / vol20.replace(0, np.nan)

    curr = float(price) if price > 0 else float(close.iloc[-1])
    signals: list[VwapSignal] = []

    curr_vwap = float(vwap20_series.iloc[-1])
    if not np.isfinite(curr_vwap):
        return []

    # 前一日收盘 vs 当日 VWAP → 判定价格从哪一侧穿越
    prev_close = float(close.iloc[-2]) if len(close) >= 2 else float(close.iloc[0])
    vol_3d = float(volume.iloc[-3:].mean())
    vol_prev = float(volume.iloc[-8:-3].mean())
    vol_ratio = vol_3d / vol_prev if vol_prev > 0 else 1.0

    # 近 5 日价格方向
    p5 = float(close.iloc[-5]) if len(close) >= 5 else float(close.iloc[0])
    price_up = curr > p5
    price_down = curr < p5

    # 价格是否从下方穿越 VWAP（前收在 VWAP 下，现价在 VWAP 上）
    crossed_up = prev_close < curr_vwap <= curr
    # 价格是否从上方跌破 VWAP（前收在 VWAP 上，现价在 VWAP 下）
    crossed_down = prev_close > curr_vwap >= curr

    # ── 事件 1: 真突破 — 价格从下方放量穿越 VWAP
    if crossed_up and price_up and vol_ratio > 1.1:
        signals.append(VwapSignal(
            "bull", 12, "vwap_band",
            f"放量站上VWAP({curr_vwap:.2f}) — 大资金在成本线接货，真突破",
            price=round(curr_vwap, 2),
            zone=f"回踩VWAP({curr_vwap:.2f})不破为确认",
        ))

    # ── 事件 2: 诱多 — VWAP 上方价涨量缩（上涨动能衰竭）
    elif curr > curr_vwap and price_up and vol_ratio < 0.8:
        signals.append(VwapSignal(
            "bear", -12, "vwap_band",
            f"VWAP上方({curr_vwap:.2f})价涨量缩 — 上涨动力不足，警惕诱多",
            price=round(curr_vwap, 2),
            zone=f"跌破VWAP({curr_vwap:.2f})确认离场",
        ))

    # ── 事件 3: 站上 VWAP（无放量，中性偏多）
    elif curr > curr_vwap and price_up:
        signals.append(VwapSignal(
            "bull", 4, "vwap_band",
            f"站上VWAP({curr_vwap:.2f})，日内趋势偏多",
            price=round(curr_vwap, 2),
        ))

    # ── 事件 4: 跌破 VWAP（含从上方穿越）
    elif curr < curr_vwap and (price_down or crossed_down):
        signals.append(VwapSignal(
            "bear", -10, "vwap_band",
            f"跌破VWAP({curr_vwap:.2f}) — 成本线下移，日内偏弱",
            price=round(curr_vwap, 2),
            zone=f"重新站回VWAP({curr_vwap:.2f})前不宜追入",
        ))

    return signals


def band_vs_ma(
    df: pd.DataFrame,
    price: float = 0.0,
    *,
    symbol: str = "",
    name: str = "",
) -> VwapBandResult:
    """VWAP 与 MA 成本带综合分析（利用点 4）。

    等价于 compute_vwap_band + detect_vwap_events 的组合，供 tactics 单点调用。
    """
    result = compute_vwap_band(df, price, symbol=symbol, name=name)
    result.signals = detect_vwap_events(df, result.price)
    result.summary = _build_summary(result)
    return result


def _build_summary(result: VwapBandResult) -> str:
    """生成成本带一句话摘要。"""
    if result.vwap20 <= 0:
        return "[DATA_GAP] VWAP 不可计算"
    parts = []
    if result.price_vs_vwap20 > 0:
        parts.append(f"现价高于20日成本 {abs(result.price_vs_vwap20):.1f}%")
    else:
        parts.append(f"现价低于20日成本 {abs(result.price_vs_vwap20):.1f}%")
    if result.band_position:
        parts.append(f"位于成本带{result.band_position}")
    if result.band_range > 0:
        parts.append(f"带宽{result.band_range:.1f}%")
    return "，".join(parts)
