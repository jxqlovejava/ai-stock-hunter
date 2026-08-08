# -*- coding: utf-8 -*-
"""P1-8 做T四要点 → 日内信号 (文章共识 @Aw3ff_ 做T技巧)。

覆盖:
  _detect_t_signals
    ① 冲高回落 → bear 信号 (高抛)
    ② 缩量急跌 → bull 信号 (低吸)
    ③ 三重低点 → bull 信号 (正T)
    ④ 信号会调整 score 并重映射 action
  _last_ascending_lows
    ⑤ 递增摆动低点 → 返回低点列表
    ⑥ 非递增/不足3个 → None

全部为纯逻辑测试, 不触发网络。
"""
from datetime import datetime

from src.data.schema import Bar
from src.analysis.t0_decision import T0DecisionEngine, T0Result

SYMBOL = "600000"


def _mk(ts, o, h, l, c, v=100):
    return Bar(symbol=SYMBOL, timestamp=ts, resolution="1min",
               open=o, high=h, low=l, close=c, volume=v, amount=0, source="test")


def _new_result(score=0):
    r = T0Result(symbol=SYMBOL)
    r.vwap = 102.0
    r.day_low = 100.0
    r.support_1 = 100.0
    r.day_high = 104.0
    r.ma5 = 103.0
    r.score = score
    return r


def test_high_pullback_signal():
    """① 冲高回落 (盘中冲高≥3% + 现价回落至高点下方2%) → 高抛 bear。"""
    engine = T0DecisionEngine()
    bars = []
    for i in range(30):
        o = 100 + i * 0.13                       # 冲到 ~103.8
        bars.append(_mk(datetime(2026, 8, 8, 9, 30 + i), o, o + 0.2, o - 0.1, o, 200))
    bars.append(_mk(datetime(2026, 8, 8, 14, 55), 103.5, 103.6, 101.0, 101.0, 150))

    r = _new_result()
    engine._detect_t_signals(r, bars)

    assert any(s.direction == "bear" and "冲高回落" in s.description
               for s in r.signals_bear)
    assert "冲高回落" in r.intraday_pattern


def test_shrink_volume_rush_drop_signal():
    """② 缩量急跌 (回撤≥2% + 后段均量≤前段0.7) → 低吸 bull。"""
    engine = T0DecisionEngine()
    bars = []
    for i in range(36):
        o = 100 + i * 0.08                       # 前段放量上行
        bars.append(_mk(datetime(2026, 8, 8, 9, (30 + i) % 60), o, o + 0.2, o - 0.05, o, 500))
    for i in range(36):
        c = 102.9 - i * 0.08                     # 后段缩量急跌
        bars.append(_mk(datetime(2026, 8, 8, 14, i), c + 0.05, c + 0.1, c - 0.05, c, 30))

    r = _new_result()
    engine._detect_t_signals(r, bars)

    assert any(s.direction == "bull" and "缩量急跌" in s.description
               for s in r.signals_bull)
    assert "缩量急跌" in r.intraday_pattern


def test_triple_low_signal():
    """③ 三重低点 (3个逐级抬高摆动低点) → 正T bull。"""
    engine = T0DecisionEngine()
    bars = []
    # 前缀 15 根缓升 (无摆动低点) → 凑足 n>=20
    for i in range(15):
        p = 100 + i * 0.1
        bars.append(_mk(datetime(2026, 8, 8, 9, 30 + i), p, p + 0.2, p - 0.05, p, 100))
    # 尾部: 3 个递增摆动低点 101 → 101.2 → 101.8
    opens = [103.0, 101.5, 101.8, 101.6, 102.3, 102.0, 102.7]
    highs = [103.5, 102.0, 102.2, 102.0, 102.6, 102.4, 103.0]
    lows = [103.0, 101.0, 101.5, 101.2, 102.0, 101.8, 102.5]
    closes = [103.0, 101.5, 101.8, 101.6, 102.3, 102.0, 102.7]
    for i in range(7):
        bars.append(_mk(datetime(2026, 8, 8, 10, 0 + i),
                        opens[i], highs[i], lows[i], closes[i], 100))

    r = _new_result()
    engine._detect_t_signals(r, bars)

    assert any(s.direction == "bull" and "三重低点" in s.description
               for s in r.signals_bull)


def test_signals_adjust_score():
    """④ 做T信号微调 score 并重映射 action。"""
    engine = T0DecisionEngine()
    bars = []
    for i in range(30):
        o = 100 + i * 0.13
        bars.append(_mk(datetime(2026, 8, 8, 9, 30 + i), o, o + 0.2, o - 0.1, o, 200))
    bars.append(_mk(datetime(2026, 8, 8, 14, 55), 103.5, 103.6, 101.0, 101.0, 150))

    r = _new_result(score=10)   # 基线 HOLD 附近, 冲高回落 -8 → 2 仍 HOLD
    engine._detect_t_signals(r, bars)

    assert r.score == 2


def test_ascending_lows_detected():
    """⑤ 递增摆动低点 → 返回低点列表。"""
    engine = T0DecisionEngine()
    lows = [103, 101, 101.5, 101.2, 102.0, 101.8, 102.5]
    out = engine._last_ascending_lows(lows)
    assert out is not None
    assert out[0] < out[1] < out[2]


def test_non_ascending_lows_none():
    """⑥ 非递增 / 不足3个 → None。"""
    engine = T0DecisionEngine()
    assert engine._last_ascending_lows([103, 101, 102, 100.5, 101.8, 100.2, 102.1]) is None
    assert engine._last_ascending_lows([102, 101, 101.5, 100.5]) is None
