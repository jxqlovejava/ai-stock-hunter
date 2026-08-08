# -*- coding: utf-8 -*-
"""P1-8 急涨缓跌/急跌缓涨形态因子 (文章共识 @LuBtc888 交易钢铁纪律 ⑬)。

覆盖:
  rush_slump_shape.compute
    ① 急跌缓涨(洗盘) → 高分 ~80
    ② 急涨缓跌(出货) → 低分 ~20
    ③ 涨跌均衡 → ~50
    ④ 单边趋势 → 退化 50 (交由趋势因子处理)

全部为纯函数测试, 不触发网络。
"""
import pandas as pd

from src.factors.zoo.ashare.technical.rush_slump_shape import compute

SYMBOL = "600000"


def _build(moves):
    idx = pd.date_range("2026-01-01", periods=len(moves) + 1, freq="B")
    closes = [100.0]
    for m in moves:
        closes.append(closes[-1] * (1 + m))
    return pd.DataFrame({SYMBOL: closes}, index=idx)


def test_washout_rush_drop_slow_recover_high_score():
    """① 急跌缓涨(洗盘): 大阴 + 小阳交替 → 高分偏多。"""
    moves = [-0.04 if i % 2 == 0 else 0.01 for i in range(59)]
    df = _build(moves)
    out = compute({"close": df})
    assert out.iloc[-1, 0] >= 70


def test_distribution_rush_rise_slow_decay_low_score():
    """② 急涨缓跌(出货): 大阳 + 小阴交替 → 低分偏空。"""
    moves = [0.04 if i % 2 == 0 else -0.01 for i in range(59)]
    df = _build(moves)
    out = compute({"close": df})
    assert out.iloc[-1, 0] <= 30


def test_balanced_score():
    """③ 涨跌同幅 → 均衡 50。"""
    moves = [0.02 if i % 2 == 0 else -0.02 for i in range(59)]
    df = _build(moves)
    out = compute({"close": df})
    assert abs(out.iloc[-1, 0] - 50.0) < 1e-6


def test_one_direction_degenerates_to_50():
    """④ 单边上涨 → 退化 50。"""
    moves = [0.01 for _ in range(59)]
    df = _build(moves)
    out = compute({"close": df})
    assert out.iloc[-1, 0] == 50.0
