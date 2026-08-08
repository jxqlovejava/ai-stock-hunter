# -*- coding: utf-8 -*-
"""P1-8 突破三分类质量分级 (文章共识 @trader_maxey 突破交易)。

覆盖:
  _detect_breakout → EntrySignal.strength
    ① 强突破 (量比≥2.0 且 突破幅度≥3%) → STRONG
    ② 弱突破 (量比<1.7 或 幅度<1.5%) → WEAK
    ③ 普通突破 → NORMAL
  _classify_breakout_strength 边界
    ④ 幅度足够但量能勉强 → WEAK
    ⑤ 量能足但幅度不足 → WEAK

全部为纯函数测试, 不触发网络。
"""
import pandas as pd

from src.routing.entry_exit_engine import EntryExitEngine

SYMBOL = "600000"


def _panel(closes, highs, vols):
    """构造宽面板 (index=date, columns=[SYMBOL])。"""
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="B")
    return (
        pd.DataFrame({SYMBOL: closes}, index=idx),
        pd.DataFrame({SYMBOL: highs}, index=idx),
        pd.DataFrame({SYMBOL: vols}, index=idx),
    )


def _base(n=25):
    """n-1 根横盘基准 (~10.2) + 1 根今日。"""
    closes = [10.0 + i * 0.01 for i in range(n - 1)]
    highs = [10.0 + i * 0.02 for i in range(n - 1)]
    vols = [100.0] * (n - 1)
    return closes, highs, vols


def test_strong_breakout():
    """① 强突破: 收盘大幅超越前高 + 量能 2.5×。"""
    closes, highs, vols = _base()
    closes.append(11.0)   # 突破幅度 ~5%
    highs.append(11.2)
    vols.append(250.0)    # 量比 2.5
    c, h, v = _panel(closes, highs, vols)

    sig = EntryExitEngine()._detect_breakout(c, h, v)
    assert sig is not None
    assert sig.strength == "STRONG"


def test_weak_breakout_by_volume():
    """② 弱突破: 量能勉强 (1.6×)。"""
    closes, highs, vols = _base()
    closes.append(10.8)   # 幅度 ~3.3%
    highs.append(11.0)
    vols.append(160.0)    # 量比 1.6 < 1.7
    c, h, v = _panel(closes, highs, vols)

    sig = EntryExitEngine()._detect_breakout(c, h, v)
    assert sig is not None
    assert sig.strength == "WEAK"
    assert sig.confidence < 0.8   # 弱势突破降置信度


def test_normal_breakout():
    """③ 普通突破: 量比 1.8 + 幅度 ~3.3%。"""
    closes, highs, vols = _base()
    closes.append(10.8)   # 幅度 ~3.3% (非 1.5% 以下, 非 2.0×)
    highs.append(11.0)
    vols.append(180.0)    # 量比 1.8
    c, h, v = _panel(closes, highs, vols)

    sig = EntryExitEngine()._detect_breakout(c, h, v)
    assert sig is not None
    assert sig.strength == "NORMAL"


def test_weak_when_excess_sufficient_but_volume_weak():
    """④ 幅度足但量能勉强 → WEAK。"""
    closes, highs, vols = _base()
    closes.append(11.0)   # 幅度 5%
    highs.append(11.2)
    vols.append(160.0)    # 量比 1.6
    c, h, v = _panel(closes, highs, vols)

    sig = EntryExitEngine()._detect_breakout(c, h, v)
    assert sig.strength == "WEAK"


def test_weak_when_volume_sufficient_but_excess_tiny():
    """⑤ 量能足但突破幅度不足 → WEAK。"""
    closes, highs, vols = _base()
    closes.append(10.5)   # 幅度 ~0.4%
    highs.append(10.7)
    vols.append(250.0)    # 量比 2.5
    c, h, v = _panel(closes, highs, vols)

    sig = EntryExitEngine()._detect_breakout(c, h, v)
    assert sig is not None
    assert sig.strength == "WEAK"
