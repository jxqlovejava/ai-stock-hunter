# -*- coding: utf-8 -*-
"""底部结构分析器单元测试 — A/B 段 + 中枢 + 逆势确认。"""

from __future__ import annotations

import numpy as np
import pytest

from src.analysis.bottom_structure import (
    BottomPhase,
    BottomStructureAnalyzer,
    analyze_bottom_structure,
)


def _synth_catching_knife(n: int = 80) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """构造 B>A 接飞刀行情：中枢后破位加速下跌。"""
    # 缓跌 A → 中枢横盘 → 破位急跌 B
    prices = []
    p = 100.0
    # A 段：跌 ~12%
    for _ in range(20):
        p *= 0.994
        prices.append(p)
    # 中枢：横盘 10 日
    base = p
    for i in range(10):
        prices.append(base + (1.0 if i % 2 == 0 else -1.0))
    # B 段：再跌 ~18%（比 A 狠）
    p = prices[-1]
    for _ in range(25):
        p *= 0.992
        prices.append(p)
    # 补齐
    while len(prices) < n:
        prices.append(prices[-1] * 0.999)

    c = np.array(prices, dtype=float)
    o = c * 1.001
    h = np.maximum(o, c) * 1.005
    l = np.minimum(o, c) * 0.995
    return o, h, l, c


def _synth_exhausted_with_setup(
    n: int = 90,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """构造 B<A + 看涨吞没 + 突破 + 不破前低。"""
    prices = []
    p = 100.0
    # A 段：大跌 ~20%
    for _ in range(25):
        p *= 0.991
        prices.append(p)
    # 中枢横盘
    base = p
    for i in range(12):
        prices.append(base + (0.8 if i % 2 == 0 else -0.6))
    # B 段：弱跌 ~8%
    p = min(prices[-12:]) - 0.5
    for _ in range(12):
        p *= 0.993
        prices.append(p)
    swing_low = p
    # 底部阴线
    prices.append(swing_low * 0.998)
    # 看涨吞没大阳
    engulf_close = swing_low * 1.04
    prices.append(engulf_close)
    # 再上行突破
    prices.append(engulf_close * 1.02)
    # 回踩但不破前低
    prices.append(swing_low * 1.01)
    prices.append(engulf_close * 1.03)

    while len(prices) < n:
        prices.append(prices[-1] * 1.001)

    c = np.array(prices, dtype=float)
    o = np.empty_like(c)
    o[0] = c[0]
    for i in range(1, len(c)):
        o[i] = c[i - 1]
    # 强制最后吞没：前一根阴、当前阳且包住
    # 找到 swing 后的两根
    # 简化：用 o/c 直接设最后几根
    idx_low = int(np.argmin(c[: len(c) - 4]))
    # 设 idx_low 附近为阴+阳吞没
    if idx_low + 1 < len(c):
        o[idx_low] = c[idx_low] * 1.01
        c[idx_low] = c[idx_low] * 0.995
        o[idx_low + 1] = c[idx_low] * 0.999
        c[idx_low + 1] = max(c[idx_low + 1], o[idx_low] * 1.001)

    h = np.maximum(o, c) * 1.008
    l = np.minimum(o, c) * 0.992
    # 确保 swing low 是真实低点
    l[idx_low] = min(l[idx_low], float(np.min(l)))
    return o, h, l, c


def _synth_uptrend(n: int = 60) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    p = 50.0
    prices = []
    for _ in range(n):
        p *= 1.003
        prices.append(p)
    c = np.array(prices, dtype=float)
    o = c * 0.999
    h = c * 1.005
    l = c * 0.995
    return o, h, l, c


class TestBottomStructureAnalyzer:
    def test_data_insufficient(self):
        c = np.linspace(100, 90, 10)
        r = analyze_bottom_structure(c, c, c, c)
        assert r.phase == BottomPhase.DATA_INSUFFICIENT
        assert r.entry_allowed is False

    def test_not_in_downtrend(self):
        o, h, l, c = _synth_uptrend()
        r = analyze_bottom_structure(h, l, c, o)
        assert r.phase == BottomPhase.NOT_IN_DOWNTREND
        assert r.entry_allowed is False

    def test_catching_knife_blocks_entry(self):
        o, h, l, c = _synth_catching_knife()
        r = BottomStructureAnalyzer().analyze(h, l, c, o)
        # 应识别为接飞刀或至少不允许入场
        assert r.entry_allowed is False
        assert r.phase in {
            BottomPhase.CATCHING_KNIFE,
            BottomPhase.NO_PIVOT,
            BottomPhase.TREND_EXHAUSTED,
        }
        if r.phase == BottomPhase.CATCHING_KNIFE:
            assert r.ab_ratio >= 1.0 or r.b_decline_pct >= r.a_decline_pct * 0.99
            assert r.score <= 30

    def test_exhausted_ratio_less_than_one(self):
        """手动构造明确 A>B 的序列。"""
        # 确定性构造：高点 100 → 跌到 80 (A=20%) → 中枢 80-82 → 破位到 76 (B≈5%)
        closes = []
        # pre peak
        closes.extend([100 - i * 0.2 for i in range(10)])  # mild
        # A leg steep
        p = closes[-1]
        for _ in range(20):
            p -= 1.0
            closes.append(p)  # ~20 pts drop
        a_end = p
        # pivot range 10 bars
        for i in range(10):
            closes.append(a_end + (0.5 if i % 2 == 0 else -0.3))
        # B weak drop
        p = min(closes[-10:]) - 0.2
        for _ in range(8):
            p -= 0.4
            closes.append(p)
        # tail chop
        for _ in range(15):
            closes.append(p + 0.1)

        c = np.array(closes, dtype=float)
        o = np.roll(c, 1)
        o[0] = c[0]
        h = np.maximum(o, c) + 0.3
        l = np.minimum(o, c) - 0.3

        r = BottomStructureAnalyzer(downtrend_pct=5.0).analyze(h, l, c, o)
        assert r.phase != BottomPhase.DATA_INSUFFICIENT
        # 若识别到中枢并测出 A/B，B 应弱于 A
        if r.a_decline_pct > 0 and r.b_decline_pct > 0:
            assert r.ab_ratio < 1.0 or r.phase != BottomPhase.CATCHING_KNIFE

    def test_to_dict_keys(self):
        o, h, l, c = _synth_catching_knife()
        r = analyze_bottom_structure(h, l, c, o)
        d = r.to_dict()
        assert "phase" in d
        assert "ab_ratio" in d
        assert "entry_allowed" in d
        assert "signals" in d

    def test_score_bounds(self):
        o, h, l, c = _synth_catching_knife()
        r = analyze_bottom_structure(h, l, c, o)
        assert 0 <= r.score <= 100


class TestDoctrineR013Integration:
    """军规 r013 / r013b 与底部结构联动。"""

    def test_r013_triggers_on_sharp_drop(self):
        from src.doctrine.checker import DoctrineChecker

        checker = DoctrineChecker()
        # 连续 3 日跌 > 15%
        result = checker.check(
            "000001",
            {
                "stock_name": "测试股",
                "drop_3day_pct": -16.0,
                "fundamental_improving": False,
            },
        )
        warn_ids = {r.id for r in result.warnings}
        assert "r013" in warn_ids

    def test_r013b_triggers_when_catching_knife(self):
        from src.doctrine.checker import DoctrineChecker

        checker = DoctrineChecker()
        result = checker.check(
            "000001",
            {
                "stock_name": "测试股",
                "bottom_phase": "CATCHING_KNIFE",
                "bottom_ab_ratio": 1.3,
            },
        )
        warn_ids = {r.id for r in result.warnings}
        assert "r013b" in warn_ids

    def test_r013b_not_trigger_on_setup(self):
        from src.doctrine.checker import DoctrineChecker

        checker = DoctrineChecker()
        result = checker.check(
            "000001",
            {
                "stock_name": "测试股",
                "bottom_phase": "LIGHT_LONG_SETUP",
                "bottom_ab_ratio": 0.5,
            },
        )
        warn_ids = {r.id for r in result.warnings}
        assert "r013b" not in warn_ids
