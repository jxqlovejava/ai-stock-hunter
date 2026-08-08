# -*- coding: utf-8 -*-
"""急涨缓跌 / 急跌缓涨 形态因子 — 涨跌速度结构判别。

文章共识 @LuBtc888 (交易钢铁纪律 ⑬): 急跌缓涨为洗盘(偏多)，急涨缓跌是出货(偏空)。

度量: 近 20 日滚动窗口内 上涨日均涨幅 / 下跌日均跌幅 的速度比。
要求窗口内多空方向并存（up_avg/down_avg 均 >0），纯单边趋势交由趋势因子处理:
  - ratio < 0.6  → 急跌缓涨(下跌快/上涨缓) = 洗盘 → 高分偏多 (~80)
  - ratio > 1.4  → 急涨缓跌(上涨快/下跌缓) = 出货 → 低分偏空 (~20)
  - 其余 / 单边方向 → 均衡 (~50)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__alpha_meta__ = {
    "id": "rush_slump_shape",
    "nickname": "Rush-Slump Shape",
    "category": "technical",
    "description": "急涨缓跌(出货)/急跌缓涨(洗盘)形态 — 涨跌速度比<0.6=洗盘(高分偏多), >1.4=出货(低分偏空)",
    "columns_required": ["close"],
    "frequency": ["daily"],
    "min_warmup_bars": 21,
}

_WINDOW = 20
_MIN_PERIODS = 10
_THRESH_WASHOUT = 0.6    # 洗盘上限 (急跌缓涨)
_THRESH_DISTRIB = 1.4    # 出货下限 (急涨缓跌)


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    close = panel["close"]
    ret = close.pct_change()
    up = ret.where(ret > 0, 0.0)
    down = ret.where(ret < 0, 0.0).abs()
    up_avg = up.rolling(_WINDOW, min_periods=_MIN_PERIODS).mean()
    down_avg = down.rolling(_WINDOW, min_periods=_MIN_PERIODS).mean()

    score = pd.DataFrame(50.0, index=close.index, columns=close.columns)
    ratio = up_avg / down_avg.replace(0, np.nan)
    both_dir = (up_avg > 0) & (down_avg > 0)
    score = score.mask((ratio < _THRESH_WASHOUT) & both_dir, 80.0)  # 急跌缓涨 → 洗盘偏多
    score = score.mask((ratio > _THRESH_DISTRIB) & both_dir, 20.0)  # 急涨缓跌 → 出货偏空
    return score.fillna(50.0)
