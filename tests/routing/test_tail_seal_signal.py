# -*- coding: utf-8 -*-
"""P1-8 封板时点 + 尾盘跳水/急拉 (文章共识 @LuBtc888 交易钢铁纪律)。

覆盖:
  _seal_time_signal
    ① 10:00前首封 → strong (连板概率大)
    ② 14:00后首封 → weak (次日易低开)
    ③ 未触及涨停 → sealed=False
  _tail_market_signal
    ④ 尾盘跳水 ≥2% → dump (隔日高开几率较高)
    ⑤ 尾盘急拉 ≥2% → pump (诱多嫌疑, 次日大多低开)
    ⑥ 尾盘平稳 → none

全部为纯函数测试, 不触发网络。
"""
from datetime import datetime

from src.data.schema import Bar
from src.routing.tactics import _seal_time_signal, _tail_market_signal

SYMBOL = "000001"
PREV_CLOSE = 10.0          # 涨停价 ≈ 11.0 (主板 10%)
LIMIT_PRICE = 11.0


def _mk(ts, o=10.0, h=10.0, l=10.0, c=10.0, v=100):
    return Bar(symbol=SYMBOL, timestamp=ts, resolution="1min",
               open=o, high=h, low=l, close=c, volume=v, amount=0, source="test")


def _session(start_min=9 * 60 + 30, n=240, price=10.0):
    """构造一段分钟线（price 为收盘价序列，或固定值）。"""
    bars = []
    for i in range(n):
        ts = datetime(2026, 8, 8, (start_min + i) // 60, (start_min + i) % 60)
        bars.append(_mk(ts, price, price, price, price))
    return bars


def test_early_seal_before_10_is_strong():
    """① 9:31 触及涨停 → strong。"""
    bars = _session(n=30, price=10.0)
    # 9:31 分 K 线 high 触涨停价
    bars.insert(0, _mk(datetime(2026, 8, 8, 9, 31), 10.5, LIMIT_PRICE, 10.4, 10.9, 500))
    out = _seal_time_signal(bars, PREV_CLOSE, SYMBOL)

    assert out["sealed"] is True
    assert out["seal_label"] == "strong"
    assert out["first_seal_time"] <= "10:00"


def test_late_seal_after_14_is_weak():
    """② 14:05 触及涨停 → weak。"""
    bars = _session(n=240, price=10.0)
    bars.append(_mk(datetime(2026, 8, 8, 14, 5), 10.5, LIMIT_PRICE, 10.4, 10.9, 500))
    out = _seal_time_signal(bars, PREV_CLOSE, SYMBOL)

    assert out["sealed"] is True
    assert out["seal_label"] == "weak"


def test_no_seal_returns_false():
    """③ 全天未触及涨停 → sealed=False。"""
    bars = _session(n=240, price=10.5)
    out = _seal_time_signal(bars, PREV_CLOSE, SYMBOL)

    assert out["sealed"] is False


def test_tail_dump_detected():
    """④ 尾盘跳水 ≥2% → dump。"""
    bars = _session(n=230, price=10.0)
    for i in range(10):   # 14:50 起从 10.0 逐根跌到 9.7 (-3%)
        ts = datetime(2026, 8, 8, 14, 50 + i)
        bars.append(_mk(ts, 10.0 - i * 0.03, 10.0, 9.7, 10.0 - i * 0.03))
    out = _tail_market_signal(bars)

    assert out["event"] == "dump"
    assert out["move_pct"] <= -2.0


def test_tail_pump_detected():
    """⑤ 尾盘急拉 ≥2% → pump。"""
    bars = _session(n=230, price=10.0)
    for i in range(10):   # 14:50 起从 10.0 逐根拉到 10.4 (+4%)
        ts = datetime(2026, 8, 8, 14, 50 + i)
        bars.append(_mk(ts, 10.0 + i * 0.04, 10.4, 10.0, 10.0 + i * 0.04))
    out = _tail_market_signal(bars)

    assert out["event"] == "pump"
    assert out["move_pct"] >= 2.0


def test_tail_flat_returns_none():
    """⑥ 尾盘平稳 → none。"""
    bars = _session(n=240, price=10.0)
    out = _tail_market_signal(bars)

    assert out["event"] == "none"
