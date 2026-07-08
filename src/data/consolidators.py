# -*- coding: utf-8 -*-
"""数据聚合器 — 将低分辨率数据聚合为高分辨率 Bar。

借鉴 LEAN Consolidators 体系 (Common/Data/Consolidators/):
  - TradeBarConsolidator:   Tick → Bar (OHLCV 聚合)
  - TimePeriodConsolidator: Bar 重采样 (1min→5min→15min→hour→day)
  - RenkoConsolidator:      价格触发砖形图 (固定价差, 忽略时间)

核心概念:
  - 输入: TickData 流 / 低分辨率 Bar 序列
  - 输出: 目标分辨率的 Bar 序列
  - 触发: 时间窗口关闭 → 输出 Bar → 重置窗口 (时间驱动)
        或价格突破阈值 → 输出砖块 → 重置砖块 (价格驱动)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Optional

import pandas as pd

from .schema import Bar, Resolution, TickData

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TradeBarConsolidator: Tick → Bar
# ---------------------------------------------------------------------------


class TradeBarConsolidator:
    """Tick 数据 → OHLCV Bar 聚合器。

    收集一个时间窗口内的所有 TickData，窗口关闭时输出一根 Bar。

    算法 (参考 LEAN TradeBarConsolidatorBase):
      - open  = 窗口内第一个 tick 的价格
      - high  = max(所有 tick 价格)
      - low   = min(所有 tick 价格)
      - close = 窗口内最后一个 tick 的价格
      - volume = 窗口末累计量 - 窗口初累计量 (避免重复计算)
      - amount = 窗口末累计额 - 窗口初累计额

    用法:
        consolidator = TradeBarConsolidator(
            symbol="600519", resolution=Resolution.MIN_1
        )
        consolidator.on_data_consumed.subscribe(lambda bar: print(bar))

        for tick in tick_stream:
            consolidator.update(tick)
    """

    def __init__(
        self,
        symbol: str,
        resolution: Resolution,
        *,
        on_bar: Callable[[Bar], None] | None = None,
    ):
        if resolution == Resolution.TICK:
            raise ValueError("TradeBarConsolidator 不支持 TICK 分辨率（无法聚合 tick→tick）")
        if resolution.total_minutes is None:
            raise ValueError(f"未知分辨率: {resolution}")

        self._symbol = symbol
        self._resolution = resolution
        self._on_bar = on_bar

        # 窗口状态
        self._window_start: datetime | None = None
        self._window_end: datetime | None = None
        self._open: float = 0.0
        self._high: float = float("-inf")
        self._low: float = float("inf")
        self._close: float = 0.0
        self._start_cumulative_vol: int = 0
        self._start_cumulative_amount: float = 0.0
        self._end_cumulative_vol: int = 0
        self._end_cumulative_amount: float = 0.0
        self._tick_count: int = 0

    def update(self, tick: TickData) -> Optional[Bar]:
        """喂入一个 Tick，窗口关闭时返回 Bar。"""
        if tick.symbol != self._symbol:
            logger.warning(
                "TradeBarConsolidator: tick symbol %s != %s，已忽略",
                tick.symbol, self._symbol,
            )
            return None

        if self._window_start is None:
            # 新窗口
            self._start_window(tick)
            return None

        if tick.timestamp >= self._window_end:  # type: ignore[operator]
            # 当前窗口关闭 → 输出 Bar
            bar = self._close_window()
            # 开启下一个窗口（可能跳过空窗期）
            self._start_window(tick)
            if self._on_bar:
                self._on_bar(bar)
            return bar

        # 仍在当前窗口内 → 更新 HL/C
        self._update_hlc(tick)
        return None

    def flush(self) -> Optional[Bar]:
        """强制关闭当前窗口（流结束时调用）。"""
        if self._window_start is None:
            return None
        bar = self._close_window()
        if self._on_bar:
            self._on_bar(bar)
        return bar

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _get_window_end(self, tick_time: datetime) -> datetime:
        """计算 tick_time 所属窗口的结束时间。

        resolution=MIN_1:
          09:30:15 → 窗口 [09:30, 09:31), 结束时间 09:31
        resolution=MIN_5:
          09:33:00 → 窗口 [09:30, 09:35), 结束时间 09:35
        """
        mins = self._resolution.total_minutes
        assert mins is not None

        midnight = tick_time.replace(hour=0, minute=0, second=0, microsecond=0)
        minutes_since_midnight = (tick_time - midnight).total_seconds() / 60
        window_idx = int(minutes_since_midnight // mins)
        return midnight + timedelta(minutes=(window_idx + 1) * mins)

    def _start_window(self, tick: TickData) -> None:
        """开启新窗口，记录第一个 tick 的数据。"""
        self._window_start = tick.timestamp
        self._window_end = self._get_window_end(tick.timestamp)
        self._open = tick.price
        self._high = tick.price
        self._low = tick.price
        self._close = tick.price
        self._start_cumulative_vol = tick.cumulative_volume
        self._start_cumulative_amount = tick.cumulative_amount
        self._end_cumulative_vol = tick.cumulative_volume
        self._end_cumulative_amount = tick.cumulative_amount
        self._tick_count = 1

    def _update_hlc(self, tick: TickData) -> None:
        """窗口内 tick → 更新 high/low/close。"""
        self._high = max(self._high, tick.price)
        self._low = min(self._low, tick.price)
        self._close = tick.price
        self._end_cumulative_vol = tick.cumulative_volume
        self._end_cumulative_amount = tick.cumulative_amount
        self._tick_count += 1

    def _close_window(self) -> Bar:
        """关闭窗口，输出 Bar。"""
        bar = Bar(
            symbol=self._symbol,
            timestamp=self._window_start,  # type: ignore[arg-type]
            resolution=self._resolution,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=self._end_cumulative_vol - self._start_cumulative_vol,
            amount=max(self._end_cumulative_amount - self._start_cumulative_amount, 0.0),
            source="consolidated",
        )
        self._reset()
        return bar

    def _reset(self) -> None:
        """重置窗口状态。"""
        self._window_start = None
        self._window_end = None
        self._open = 0.0
        self._high = float("-inf")
        self._low = float("inf")
        self._close = 0.0
        self._tick_count = 0


# ---------------------------------------------------------------------------
# TimePeriodConsolidator: Bar 重采样
# ---------------------------------------------------------------------------


class TimePeriodConsolidator:
    """Bar 时间周期重采样。

    输入低周期 Bar 序列，输出高周期 Bar 序列。
    用 pandas DataFrame.resample() 实现，比逐 tick 聚合更高效。

    用法:
        consolidator = TimePeriodConsolidator(
            target_resolution=Resolution.MIN_15
        )
        bars_15min = consolidator.consolidate(bars_1min)
    """

    def __init__(self, target_resolution: Resolution):
        if target_resolution == Resolution.TICK:
            raise ValueError("TimePeriodConsolidator 不支持 TICK 目标分辨率")
        if target_resolution.pandas_freq is None:
            raise ValueError(f"未知目标分辨率: {target_resolution}")
        self._target = target_resolution

    def consolidate(self, bars: list[Bar]) -> list[Bar]:
        """将低分辨率 Bar 列表聚合为目标分辨率 Bar 列表。

        聚合规则 (参考 LEAN TradeBarConsolidator):
          - open  = 区间首 Bar 的 open
          - high  = 区间 max(high)
          - low   = 区间 min(low)
          - close = 区间末 Bar 的 close
          - volume = 区间 sum(volume)
          - amount = 区间 sum(amount)
        """
        if not bars:
            return []

        df = self._bars_to_dataframe(bars)
        freq = self._target.pandas_freq
        assert freq is not None

        resampled = df.resample(freq, label="left", closed="left").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "amount": "sum",
        }).dropna()

        symbol = bars[0].symbol
        return [
            Bar(
                symbol=symbol,
                timestamp=idx.to_pydatetime(),
                resolution=self._target,
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=int(row["volume"]),
                amount=float(row["amount"]),
                source=bars[0].source,
            )
            for idx, row in resampled.iterrows()
        ]

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    @staticmethod
    def _bars_to_dataframe(bars: list[Bar]) -> pd.DataFrame:
        """Bar 列表 → 以 timestamp 为索引的 DataFrame。"""
        records = [
            {
                "timestamp": b.timestamp,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "amount": b.amount,
            }
            for b in bars
        ]
        df = pd.DataFrame(records)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df.set_index("timestamp").sort_index()


# ---------------------------------------------------------------------------
# 工具函数：批量 Bar 转换
# ---------------------------------------------------------------------------


def bars_to_dataframe(bars: list[Bar]) -> pd.DataFrame:
    """Bar 列表 → pandas DataFrame（标准 OHLCV 列）。

    返回列: timestamp, symbol, open, high, low, close, volume, amount, resolution
    索引为 timestamp。
    """
    if not bars:
        return pd.DataFrame(
            columns=["timestamp", "symbol", "open", "high", "low", "close",
                      "volume", "amount", "resolution"],
        ).set_index("timestamp")

    records = [b.to_dict() for b in bars]
    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp")


def dataframe_to_bars(
    df: pd.DataFrame,
    symbol: str,
    resolution: Resolution,
    source: str = "",
) -> list[Bar]:
    """DataFrame → Bar 列表。

    要求 df 包含列: open, high, low, close, volume（可选 amount）。
    index 必须是 DatetimeIndex。
    """
    bars = []
    for idx, row in df.iterrows():
        bars.append(Bar(
            symbol=symbol,
            timestamp=idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx,
            resolution=resolution,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=int(row.get("volume", 0)),
            amount=float(row.get("amount", 0.0)),
            source=source,
        ))
    return bars


# ---------------------------------------------------------------------------
# RenkoConsolidator — 参照 LEAN RenkoConsolidator (Wicked 类型)
# ---------------------------------------------------------------------------


class RenkoDirection(str, Enum):
    """砖形图方向。"""
    RISING = "rising"
    FALLING = "falling"


@dataclass(frozen=True)
class RenkoBar:
    """Renko 砖块 — 价格触发而非时间触发的 Bar。

    参照 LEAN RenkoBar (Common/Data/Market/RenkoBar.cs):
      - symbol, time, end_time
      - bar_size (固定价差)
      - open, high, low, close
      - direction (RISING/FALLING)
      - is_closed (是否已封闭) — 未封闭的砖仍在构建中
    """

    symbol: str
    timestamp: datetime
    end_timestamp: datetime
    bar_size: float
    open: float
    high: float
    low: float
    close: float
    direction: RenkoDirection
    is_closed: bool = True
    source: str = "renko"


class RenkoConsolidator:
    """Renko (砖形图) 聚合器 — Wicked 类型。

    将 tick/bar 数据流转换为固定价差砖块流。不依赖时间轴，
    当价格突破 brick_size 时产生新砖块。

    算法 (参照 LEAN RenkoConsolidator Wicked type):
      1. 首 tick → 四舍五入到最近的 bar_size 倍数作为 open
      2. 价格上升超过 open + bar_size → 产生上升砖 (RISING)
      3. 价格下跌超过 open - bar_size → 产生下跌砖 (FALLING)
      4. Wicked 类型保留实际 high/low 作为影线
      5. 方向反转时先出反砖 (wicko) 再出顺向砖

    用法:
        renko = RenkoConsolidator(symbol="600519", bar_size=0.5)
        renko.on_bar_created.subscribe(lambda b: print(f"{b.direction}: {b.open}→{b.close}"))
        for bar in minute_bars:
            renko.update(bar.close, bar.timestamp, bar.high, bar.low)
    """

    def __init__(
        self,
        symbol: str,
        bar_size: float,
        *,
        on_bar: Callable[[RenkoBar], None] | None = None,
    ):
        if bar_size <= 0:
            raise ValueError(f"bar_size 必须 > 0, got {bar_size}")
        self._symbol = symbol
        self._bar_size = bar_size
        self._on_bar = on_bar

        # 窗口状态 (参照 LEAN RenkoConsolidator 字段)
        self._first_tick = True
        self._last_wicko: RenkoBar | None = None
        self._open_on: datetime | None = None
        self._close_on: datetime | None = None
        self._open_rate: float = 0.0
        self._high_rate: float = float("-inf")
        self._low_rate: float = float("inf")
        self._close_rate: float = 0.0

    def update(
        self, price: float, timestamp: datetime | None = None,
        high: float | None = None, low: float | None = None,
    ) -> list[RenkoBar]:
        """喂入新价格，返回新产生的砖块列表。

        Args:
            price: 当前价格 (通常用 close)
            timestamp: 时间戳
            high: 该时间段最高价 (Wicked 模式需要)
            low: 该时间段最低价 (Wicked 模式需要)

        Returns:
            新产生的 RenkoBar 列表（可能为空、1 个或多个）
        """
        emitted: list[RenkoBar] = []
        ts = timestamp or datetime.now()
        h = high if high is not None else price
        l = low if low is not None else price

        if self._first_tick:
            self._first_tick = False
            # round to nearest bar_size multiple (LEAN GetClosestMultiple)
            rounded = self._round_to_bar_size(price)
            self._open_on = ts
            self._close_on = ts
            self._open_rate = rounded
            self._high_rate = h
            self._low_rate = l
            self._close_rate = price
            return emitted

        self._close_on = ts
        self._high_rate = max(self._high_rate, h)
        self._low_rate = min(self._low_rate, l)
        self._close_rate = price

        if price > self._open_rate:
            if self._last_wicko is None or self._last_wicko.direction == RenkoDirection.RISING:
                emitted.extend(self._rising(ts))
            else:
                # 方向反转 (falling→rising): 先出反砖 wicko
                limit = self._last_wicko.open + self._bar_size
                if price > limit:
                    wicko = RenkoBar(
                        symbol=self._symbol,
                        timestamp=self._open_on,  # type: ignore[arg-type]
                        end_timestamp=self._close_on,  # type: ignore[arg-type]
                        bar_size=self._bar_size,
                        open=self._last_wicko.open,
                        high=limit,
                        low=self._low_rate,
                        close=limit,
                        direction=RenkoDirection.RISING,
                        source=self._symbol,
                    )
                    self._last_wicko = wicko
                    emitted.append(wicko)
                    self._open_on = self._close_on
                    self._open_rate = limit
                    self._low_rate = limit
                    emitted.extend(self._rising(ts))

        elif price < self._open_rate:
            if self._last_wicko is None or self._last_wicko.direction == RenkoDirection.FALLING:
                emitted.extend(self._falling(ts))
            else:
                # 方向反转 (rising→falling): 先出反砖 wicko
                limit = self._last_wicko.open - self._bar_size
                if price < limit:
                    wicko = RenkoBar(
                        symbol=self._symbol,
                        timestamp=self._open_on,  # type: ignore[arg-type]
                        end_timestamp=self._close_on,  # type: ignore[arg-type]
                        bar_size=self._bar_size,
                        open=self._last_wicko.open,
                        high=self._high_rate,
                        low=limit,
                        close=limit,
                        direction=RenkoDirection.FALLING,
                        source=self._symbol,
                    )
                    self._last_wicko = wicko
                    emitted.append(wicko)
                    self._open_on = self._close_on
                    self._open_rate = limit
                    self._high_rate = limit
                    emitted.extend(self._falling(ts))

        for bar in emitted:
            if self._on_bar:
                self._on_bar(bar)

        return emitted

    def reset(self) -> None:
        """重置状态。"""
        self._first_tick = True
        self._last_wicko = None
        self._open_on = None
        self._close_on = None
        self._open_rate = 0.0
        self._high_rate = float("-inf")
        self._low_rate = float("inf")
        self._close_rate = 0.0

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _rising(self, ts: datetime) -> list[RenkoBar]:
        """上升方向 → 产生一个或多个 RISING 砖块。"""
        emitted = []
        while self._close_rate > (limit := self._open_rate + self._bar_size):
            bar = RenkoBar(
                symbol=self._symbol,
                timestamp=self._open_on,  # type: ignore[arg-type]
                end_timestamp=self._close_on,  # type: ignore[arg-type]
                bar_size=self._bar_size,
                open=self._open_rate,
                high=limit,
                low=self._low_rate,
                close=limit,
                direction=RenkoDirection.RISING,
                source=self._symbol,
            )
            self._last_wicko = bar
            emitted.append(bar)
            self._open_on = self._close_on
            self._open_rate = limit
            self._low_rate = limit
        return emitted

    def _falling(self, ts: datetime) -> list[RenkoBar]:
        """下跌方向 → 产生一个或多个 FALLING 砖块。"""
        emitted = []
        while self._close_rate < (limit := self._open_rate - self._bar_size):
            bar = RenkoBar(
                symbol=self._symbol,
                timestamp=self._open_on,  # type: ignore[arg-type]
                end_timestamp=self._close_on,  # type: ignore[arg-type]
                bar_size=self._bar_size,
                open=self._open_rate,
                high=self._high_rate,
                low=limit,
                close=limit,
                direction=RenkoDirection.FALLING,
                source=self._symbol,
            )
            self._last_wicko = bar
            emitted.append(bar)
            self._open_on = self._close_on
            self._open_rate = limit
            self._high_rate = limit
        return emitted

    def _round_to_bar_size(self, price: float) -> float:
        """价格四舍五入到最近的 bar_size 倍数。

        参照 LEAN RenkoConsolidator.GetClosestMultiple():
          基于 Knuth TAOCP Vol 1, p39.
        """
        if self._bar_size <= 0:
            return price
        floor_part = price // self._bar_size
        modulus = price - self._bar_size * floor_part
        round_offset = round(modulus / self._bar_size)
        return self._bar_size * (floor_part + round_offset)
