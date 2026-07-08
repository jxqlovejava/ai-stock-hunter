# -*- coding: utf-8 -*-
"""数据馈送抽象 — 统一回测与实盘的数据订阅管道。

借鉴 LEAN 的 IDataFeed + Subscription + FillForward 三层架构:

  DataFeed (Protocol)
    └── HistoricalDataFeed      — 回测用，从 DataProvider 拉取历史 Bar
    └── (LiveDataFeed 预留)      — 实盘用，从 mootdx/腾讯实时推送

  Subscription                   — 追踪单个 symbol+resolution 的订阅状态
    ├── SubscriptionConfig       — 订阅配置 (参照 LEAN SubscriptionDataConfig)
    ├── FillForwardEnumerator    — 数据间隙填充 (参照 LEAN FillForwardEnumerator)
    └── _SubscriptionManager     — 订阅集合管理 (参照 LEAN SubscriptionCollection)

核心概念:
  - 订阅 = symbol + resolution + fill_forward + consolidators
  - 数据流 = Bar 序列 → FillForward → Consolidators → on_data 回调
  - 管理器 = 所有活跃订阅的集合，统一推进时间
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Generator, Optional, Protocol

from .base import DataProvider
from .schema import Bar, Resolution

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SubscriptionConfig — 参照 LEAN SubscriptionDataConfig
# ---------------------------------------------------------------------------


@dataclass
class SubscriptionConfig:
    """订阅配置 — 定义单个数据订阅的全部参数。

    参照 LEAN SubscriptionDataConfig:
      - Type (data type) / Symbol / Resolution / TickType
      - FillDataForward / ExtendedMarketHours
      - Consolidators set
      - DataTimeZone / ExchangeTimeZone

    A 股版简化为核心字段，去掉了多资产类型、时区等。
    """

    symbol: str
    resolution: Resolution
    fill_forward: bool = True
    extended_hours: bool = False  # A 股暂不支持盘前盘后

    def __hash__(self) -> int:
        return hash((self.symbol, self.resolution))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SubscriptionConfig):
            return False
        return self.symbol == other.symbol and self.resolution == other.resolution

    @property
    def increment(self) -> timedelta:
        """该分辨率的时间增量。"""
        mins = self.resolution.total_minutes
        if mins is None:
            return timedelta(seconds=3)  # tick 默认 3s
        return timedelta(minutes=mins)


# ---------------------------------------------------------------------------
# FillForwardEnumerator — 参照 LEAN FillForwardEnumerator
# ---------------------------------------------------------------------------


class FillForwardEnumerator:
    """数据前向填充枚举器。

    当两个 Bar 之间存在时间间隙时（如停牌、午休、数据缺失），
    用最近的已知 Bar 填充间隙，确保时间轴连续无空洞。

    算法 (参照 LEAN FillForwardEnumerator):
      1. 维护 last_bar 指针
      2. 遍历数据流，发现 gap (next.time > last.end_time + increment)
      3. 在 gap 中插入 fill-forward bar: clone(last_bar) with time += increment
      4. fill-forward bar 最多重复 N 次 (max_fill_forward_span)

    用法:
        ff = FillForwardEnumerator(resolution=Resolution.MIN_1)
        for bar in ff.enumerate(raw_bars):
            process(bar)
    """

    def __init__(
        self,
        resolution: Resolution,
        max_fill_forward_span: int = 100,
        data_feed: Optional[HistoricalDataFeed] = None,
    ):
        self._resolution = resolution
        self._max_span = max_fill_forward_span
        self._data_feed = data_feed
        self._last_bar: Bar | None = None

    def enumerate(self, bars: list[Bar]) -> Generator[Bar, None, None]:
        """将 Bar 列表转换为无间隙的数据流。"""
        if not bars:
            return

        inc = timedelta(minutes=self._resolution.total_minutes) if self._resolution.total_minutes else None
        if inc is None:
            yield from bars
            return

        for bar in bars:
            # 填充上一个 bar 到当前 bar 之间的间隙
            if self._last_bar is not None:
                expected = self._last_bar.timestamp + inc
                gap_count = 0
                while expected < bar.timestamp and gap_count < self._max_span:
                    yield self._create_fill_forward(bar=bar, timestamp=expected)
                    expected += inc
                    gap_count += 1

            yield bar
            self._last_bar = bar

    def _create_fill_forward(self, bar: Bar, timestamp: datetime) -> Bar:
        """创建填充 Bar: clone 上一个 Bar，更新 timestamp。"""
        assert self._last_bar is not None
        return Bar(
            symbol=bar.symbol,
            timestamp=timestamp,
            resolution=self._resolution,
            open=self._last_bar.close,
            high=self._last_bar.close,
            low=self._last_bar.close,
            close=self._last_bar.close,
            volume=0,
            amount=0.0,
            source=f"fill_forward({self._last_bar.source})",
        )


# ---------------------------------------------------------------------------
# Subscription — 参照 LEAN Subscription (Engine/DataFeeds/Subscription.cs)
# ---------------------------------------------------------------------------


class Subscription:
    """单个数据订阅 — 管理一个 symbol+resolution 的完整数据管道。

    参照 LEAN Subscription:
      - Configuration / Security / TimeZone
      - NewDataAvailable 事件
      - EndOfStream 标记
      - 作为 IEnumerator<SubscriptionData> 迭代器

    管道: 原始数据 → FillForward → Consolidators → on_bar 回调
    """

    def __init__(
        self,
        config: SubscriptionConfig,
        bars: list[Bar],
        *,
        on_bar: Callable[[Bar], None] | None = None,
    ):
        self.config = config
        self._bars = bars
        self._on_bar = on_bar
        self._index = 0
        self._fill_forward: FillForwardEnumerator | None = (
            FillForwardEnumerator(config.resolution) if config.fill_forward else None
        )
        self._consolidators: list = []  # 注册的 IDataConsolidator
        self.end_of_stream = False

    def move_next(self) -> Bar | None:
        """推进到下一个 Bar（含 fill-forward 填充）。返回 None 表示流结束。"""
        if self._index >= len(self._bars):
            self.end_of_stream = True
            return None

        bar = self._bars[self._index]
        self._index += 1

        # 通过 consolidator 管道（如有注册）
        for c in self._consolidators:
            result = c.update(bar)
            if result is not None:
                bar = result

        return bar

    def peek(self) -> Bar | None:
        """查看下一个 Bar 但不推进指针。"""
        if self._index >= len(self._bars):
            return None
        return self._bars[self._index]

    def add_consolidator(self, consolidator) -> None:
        """注册数据聚合器（如 1min→5min 聚合器）。"""
        self._consolidators.append(consolidator)

    def __repr__(self) -> str:
        return f"Subscription({self.config.symbol}, {self.config.resolution.value}, ff={self.config.fill_forward})"


# ---------------------------------------------------------------------------
# SubscriptionManager — 参照 LEAN SubscriptionCollection
# ---------------------------------------------------------------------------


class SubscriptionManager:
    """订阅集合管理器 — 管理所有活跃订阅。

    参照 LEAN SubscriptionCollection:
      - ConcurrentDictionary<SubscriptionDataConfig, Subscription>
      - TryAdd / TryGetValue / TryRemove
      - FillForwardResolution 自动计算（取最小非 tick resolution）
      - SortSubscriptions (按 security type / tick type / symbol 排序)
    """

    def __init__(self):
        self._subscriptions: dict[SubscriptionConfig, Subscription] = {}

    def add(self, sub: Subscription) -> bool:
        """添加订阅。已存在相同配置则忽略。"""
        if sub.config in self._subscriptions:
            return False
        self._subscriptions[sub.config] = sub
        return True

    def remove(self, config: SubscriptionConfig) -> Subscription | None:
        """移除订阅。"""
        return self._subscriptions.pop(config, None)

    def get(self, config: SubscriptionConfig) -> Subscription | None:
        """获取订阅。"""
        return self._subscriptions.get(config)

    def __iter__(self):
        """按 symbol 排序返回所有订阅。"""
        return iter(sorted(self._subscriptions.values(), key=lambda s: s.config.symbol))

    def __len__(self) -> int:
        return len(self._subscriptions)

    @property
    def fill_forward_resolution(self) -> timedelta:
        """自动计算最小非 tick FillForward 分辨率。

        参照 LEAN SubscriptionCollection.UpdateAndGetFillForwardResolution():
        取所有非 tick 订阅中 resolution 最小的作为 fill-forward 间隔。
        """
        res_list = [
            s.config.resolution
            for s in self._subscriptions.values()
            if s.config.fill_forward and s.config.resolution != Resolution.TICK
        ]
        if not res_list:
            return timedelta(minutes=1)
        mins = min(r.total_minutes for r in res_list if r.total_minutes is not None)
        return timedelta(minutes=mins)

    @property
    def all_end_of_stream(self) -> bool:
        """所有订阅是否都已流结束。"""
        return all(s.end_of_stream for s in self._subscriptions.values())


# ---------------------------------------------------------------------------
# DataFeed Protocol — 参照 LEAN IDataFeed
# ---------------------------------------------------------------------------


class DataFeed(Protocol):
    """数据馈送协议。

    参照 LEAN IDataFeed:
      - Initialize(algorithm, job, ...)
      - CreateSubscription(request) → Subscription
      - RemoveSubscription(subscription)
      - Exit()
    """

    def initialize(self, provider: DataProvider) -> None:
        """初始化数据馈送。"""
        ...

    def create_subscription(
        self, symbol: str, resolution: Resolution,
        start: str = "", end: str = "",
        fill_forward: bool = True,
    ) -> Subscription:
        """创建数据订阅。"""
        ...

    def remove_subscription(self, config: SubscriptionConfig) -> None:
        """移除数据订阅。"""
        ...


# ---------------------------------------------------------------------------
# HistoricalDataFeed — 参照 LEAN BacktestingDataFeed 模式
# ---------------------------------------------------------------------------


class HistoricalDataFeed:
    """历史数据馈送 — 从 DataProvider 拉取历史 Bar 创建订阅。

    参照 LEAN 回测模式:
      - FileSystemDataFeed 从磁盘读取历史数据
      - 每个订阅独立枚举，FillForward 填充间隙
      - TimeSliceFactory 合并各订阅数据为时间片

    用法:
        feed = HistoricalDataFeed()
        feed.initialize(provider)
        sub = feed.create_subscription("600519", Resolution.MIN_1,
                                       start="20250701", end="20250708")
        for bar in feed.stream():
            strategy.on_bar(bar)
    """

    def __init__(self, provider: DataProvider | None = None):
        self._provider = provider
        self._manager = SubscriptionManager()
        self._current_time: datetime | None = None

    def initialize(self, provider: DataProvider) -> None:
        """绑定数据源。"""
        self._provider = provider

    def create_subscription(
        self, symbol: str, resolution: Resolution,
        start: str = "", end: str = "",
        fill_forward: bool = True,
    ) -> Subscription:
        """从 DataProvider 拉取历史 Bar 并创建订阅。

        Args:
            symbol: 6 位股票代码
            resolution: 时间分辨率
            start: 起始日期 YYYYMMDD
            end: 结束日期 YYYYMMDD
            fill_forward: 是否填充数据间隙

        Returns:
            Subscription 对象
        """
        if self._provider is None:
            raise RuntimeError("HistoricalDataFeed 未初始化，请先调用 initialize(provider)")

        config = SubscriptionConfig(
            symbol=symbol,
            resolution=resolution,
            fill_forward=fill_forward,
        )

        bars = self._provider.get_bars(symbol, resolution, start=start, end=end)
        sub = Subscription(config, bars)
        self._manager.add(sub)
        return sub

    def remove_subscription(self, config: SubscriptionConfig) -> None:
        """移除订阅。"""
        self._manager.remove(config)

    def stream(self) -> Generator[Bar, None, None]:
        """流式输出所有订阅的 Bar — 按时间合并。

        参照 LEAN TimeSliceFactory:
          合并所有订阅的当前 Bar，按时间排序统一输出。
          每个时间步只输出最早的未消费 Bar。

        Yields:
            Bar: 下一个按时间排序的 Bar
        """
        while not self._manager.all_end_of_stream:
            # 每个订阅查看下一个 Bar
            candidates: list[tuple[Subscription, Bar]] = []
            for sub in self._manager:
                bar = sub.peek()
                if bar is not None:
                    candidates.append((sub, bar))

            if not candidates:
                break

            # 取时间最早的 Bar
            candidates.sort(key=lambda x: x[1].timestamp)
            earliest_sub, earliest_bar = candidates[0]
            earliest_sub.move_next()  # 消费该 Bar
            self._current_time = earliest_bar.timestamp
            yield earliest_bar

    @property
    def current_time(self) -> datetime | None:
        """当前数据流时间。"""
        return self._current_time

    @property
    def subscriptions(self) -> SubscriptionManager:
        """所有活跃订阅。"""
        return self._manager
