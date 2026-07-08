# -*- coding: utf-8 -*-
"""迁移适配层 — bt.Strategy → BaizeStrategy 兼容桥接。

帮助现有 MVP 策略 (继承 bt.Strategy) 平滑迁移到 BaizeStrategy。

用法:
  # 方式 1: 手动迁移 (推荐)
  class MVP1Strategy(BaizeStrategy):  # 改父类
      def next(self):
          for data in self.datas:
              if data.close[-1] > data.close[-20]:
                  self.buy(data)

  # 方式 2: 使用兼容桥接 (临时)
  from src.backtest.migration import bt_to_baize
  MigratedMVP1 = bt_to_baize(MVP1StrategyBT)

API 映射:
  Backtrader              → BaizeStrategy
  ───────────────────────────────────────────
  self.datas[i].close[0]  → self.datas[i].close[-1]
  self.data.close[0]      → self.data.close[-1]
  self.getposition(d).size → self.getposition(d)
  self.buy(data=d, size=N) → self.buy(d, size=N)
  self.sell(data=d, size=N)→ self.sell(d, size=N)
  self.close(data=d)       → self.close(d)
  self.broker.getvalue()   → self.getvalue()
  self.broker.getcash()    → self.getcash()
  d._name                  → d.symbol
  self.p.param_name        → self.params["param_name"]
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backtest.strategy import BaizeStrategy
    from src.backtest.cerebro import BaizeDataFeed

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Data feed 增强器 — 让 BaizeDataFeed 支持 bt-like 索引访问
# ------------------------------------------------------------------

def _make_data_bt_compatible(data: "BaizeDataFeed"):
    """给 BaizeDataFeed 注入 bt.Strategy 兼容属性。

    注入:
      - data.lines.close[0] → data.close[-1]
      - data._name → data.symbol
    """
    # 创建 lines 模拟对象
    class _Lines:
        def __init__(self, feed):
            self.close = _LineAccessor(feed.close)
            self.open = _LineAccessor(feed.open)
            self.high = _LineAccessor(feed.high)
            self.low = _LineAccessor(feed.low)
            self.volume = _LineAccessor(feed.volume)

    class _LineAccessor:
        """模拟 Backtrader LineBuffer 的索引访问。
        [-1] = 当前 bar, [-2] = 上一 bar
        """
        def __init__(self, series):
            import pandas as pd
            self._series = series if isinstance(series, pd.Series) else pd.Series(series)
            self._buf = list(self._series.values)

        def __getitem__(self, idx):
            if idx >= 0:
                return self._buf[idx]
            # 负索引: -1→最后一个
            if abs(idx) <= len(self._buf):
                return self._buf[idx]
            return 0.0

    if not hasattr(data, "_bt_lines"):
        data._bt_lines = _Lines(data)
        data.lines = data._bt_lines
        data._name = data.symbol

    return data


# ------------------------------------------------------------------
# Strategy 适配器
# ------------------------------------------------------------------

def bt_to_baize(bt_strategy_cls):
    """将 bt.Strategy 子类转换为 BaizeStrategy 子类。

    Args:
        bt_strategy_cls: 继承 bt.Strategy 的类

    Returns:
        新的 BaizeStrategy 子类
    """
    from src.backtest.strategy import BaizeStrategy

    class _MigratedStrategy(BaizeStrategy):
        """由 bt.Strategy 迁移而来的策略。"""

        def __init__(self, cerebro, **params):
            super().__init__(cerebro, **params)
            # 创建 self.p 兼容对象
            self.p = _ParamsProxy(self.params)

            # 实例化原始策略的核心逻辑
            self._bt_orig = None
            if hasattr(bt_strategy_cls, "__init__"):
                try:
                    self._bt_orig = bt_strategy_cls.__new__(bt_strategy_cls)
                    # 复制 params
                    if hasattr(bt_strategy_cls, "params"):
                        bt_params = dict(bt_strategy_cls.params._getpairs())
                        self.params.update(bt_params)
                        self.p = _ParamsProxy(self.params)
                except Exception:
                    pass

        def next(self):
            # 使 datas 兼容 bt 访问
            for data in self.datas:
                _make_data_bt_compatible(data)

            # 调用原始策略的 next
            if hasattr(bt_strategy_cls, "next"):
                # 临时替换 self 属性
                orig_datas = getattr(self._bt_orig, "datas", None) if self._bt_orig else None
                orig_data = getattr(self._bt_orig, "data", None) if self._bt_orig else None

                try:
                    if self._bt_orig:
                        self._bt_orig.datas = [_make_data_bt_compatible(d) for d in self.datas]
                        self._bt_orig.data = self._bt_orig.datas[0] if self._bt_orig.datas else None
                        bt_strategy_cls.next(self._bt_orig)
                except Exception as e:
                    logger.warning(f"Migrated strategy next() error: {e}")
                finally:
                    if self._bt_orig and orig_datas is not None:
                        self._bt_orig.datas = orig_datas

        def buy(self, data=None, size=None, price=None, **kwargs):
            if "data" in kwargs:
                data = kwargs.pop("data")
            return super().buy(data, size, price, **kwargs)

        def sell(self, data=None, size=None, price=None, **kwargs):
            if "data" in kwargs:
                data = kwargs.pop("data")
            return super().sell(data, size, price, **kwargs)

        def close(self, data=None, **kwargs):
            if "data" in kwargs:
                data = kwargs.pop("data")
            return super().close(data)

    _MigratedStrategy.__name__ = f"Migrated{bt_strategy_cls.__name__}"
    _MigratedStrategy.__doc__ = f"Migrated from {bt_strategy_cls.__name__}"

    return _MigratedStrategy


class _ParamsProxy:
    """让 self.p.xxx 映射到 self.params["xxx"]。"""

    def __init__(self, params: dict):
        self._params = params

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._params.get(name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            self._params[name] = value
