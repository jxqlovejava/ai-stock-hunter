# -*- coding: utf-8 -*-
"""KellyPositionSizer 测试 — 冷启动/热启动 + 凯利公式计算。"""

import tempfile
from pathlib import Path

import pytest

from src.kelly.sizer import KellyPositionSizer, SizingResult
from src.kelly.tracker import KellyParams, TradeRecord, TradeTracker


class TestKellyPositionSizer:
    """KellyPositionSizer 仓位计算测试。"""

    @pytest.fixture
    def hot_tracker(self):
        """创建有 5+ 笔混合交易记录的 tracker（热启动）。"""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trades.json"
            tracker = TradeTracker(path=path)
            # 3 wins at +10%, 2 losses at -5%
            for _ in range(3):
                tracker.track(TradeRecord(
                    symbol="600519", entry_date="2026-01-15", exit_date="2026-01-20",
                    entry_price=100.0, exit_price=110.0,
                ))
            for _ in range(2):
                tracker.track(TradeRecord(
                    symbol="600519", entry_date="2026-02-01", exit_date="2026-02-10",
                    entry_price=100.0, exit_price=95.0,
                ))
            yield tracker

    @pytest.fixture
    def cold_tracker(self):
        """创建只有 3 笔记录的 tracker（冷启动）。"""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trades.json"
            tracker = TradeTracker(path=path)
            for _ in range(3):
                tracker.track(TradeRecord(
                    symbol="000001", entry_date="2026-01-15", exit_date="2026-01-20",
                    entry_price=50.0, exit_price=55.0,
                ))
            yield tracker

    @pytest.fixture
    def empty_tracker(self):
        """空 tracker（无交易记录）。"""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trades.json"
            yield TradeTracker(path=path)

    # ------------------------------------------------------------------
    # 热启动测试
    # ------------------------------------------------------------------

    def test_hot_start_kelly(self, hot_tracker: TradeTracker):
        """热启动 (n=5, p=0.6, b=2.0) → half-Kelly。"""
        sizer = KellyPositionSizer(hot_tracker, default_kelly_fraction=0.5)
        result = sizer.calc("600519", score=70, macro_cap=0.80)

        assert result.method == "kelly"
        # f* = (2.0 × 0.6 - 0.4) / 2.0 = 0.4
        assert result.kelly_f == pytest.approx(0.4)
        # half-Kelly = 0.5 × 0.4 = 0.20
        assert result.target_weight == pytest.approx(0.20)
        assert result.n_trades == 5
        assert result.win_rate == 0.6
        assert result.payoff_ratio == pytest.approx(2.0)

    def test_hot_start_full_kelly(self, hot_tracker: TradeTracker):
        """热启动 + full-Kelly (fraction=1.0)。"""
        sizer = KellyPositionSizer(hot_tracker, default_kelly_fraction=0.5)
        result = sizer.calc("600519", score=70, macro_cap=0.80, kelly_fraction=1.0)

        assert result.method == "kelly"
        assert result.target_weight == pytest.approx(0.4)  # full f*

    def test_hot_start_quarter_kelly(self, hot_tracker: TradeTracker):
        """热启动 + quarter-Kelly (fraction=0.25)。"""
        sizer = KellyPositionSizer(hot_tracker, default_kelly_fraction=0.5)
        result = sizer.calc("600519", score=70, macro_cap=0.80, kelly_fraction=0.25)

        assert result.target_weight == pytest.approx(0.10)  # 0.25 × 0.4

    def test_hot_start_l4_cap(self, hot_tracker: TradeTracker):
        """凯利仓位被风控单票上限裁剪。"""
        sizer = KellyPositionSizer(hot_tracker, default_kelly_fraction=1.0)
        result = sizer.calc(
            "600519", score=70, macro_cap=0.80,
            position_limits={"single_stock_cap": 0.15},
        )
        # f* = 0.4, 但被 cap 到 0.15
        assert result.target_weight == 0.15

    def test_hot_start_macro_cap(self, hot_tracker: TradeTracker):
        """凯利仓位被 macro_cap 裁剪。"""
        sizer = KellyPositionSizer(hot_tracker, default_kelly_fraction=1.0)
        result = sizer.calc("600519", score=70, macro_cap=0.25)
        # f* = 0.4, 但被 macro_cap=0.25 限制
        assert result.target_weight == 0.25

    # ------------------------------------------------------------------
    # 冷启动测试
    # ------------------------------------------------------------------

    def test_cold_start_linear(self, cold_tracker: TradeTracker):
        """冷启动 (n=3<5) → 回退线性公式。"""
        sizer = KellyPositionSizer(cold_tracker, default_kelly_fraction=0.5)
        result = sizer.calc("000001", score=70, macro_cap=0.80)

        assert result.method == "linear_fallback"
        # base = (70 - 50) / 50 × 0.80 = 0.32
        assert result.target_weight == pytest.approx(0.32)
        assert result.n_trades == 3

    def test_empty_tracker_linear(self, empty_tracker: TradeTracker):
        """空 tracker → 线性回退。"""
        sizer = KellyPositionSizer(empty_tracker, default_kelly_fraction=0.5)
        result = sizer.calc("000001", score=75, macro_cap=0.80)

        assert result.method == "linear_fallback"
        # base = (75 - 50) / 50 × 0.80 = 0.40
        assert result.target_weight == pytest.approx(0.40)
        assert result.n_trades == 0

    def test_cold_start_l4_cap(self, cold_tracker: TradeTracker):
        """冷启动线性回退也被风控裁剪。"""
        sizer = KellyPositionSizer(cold_tracker, default_kelly_fraction=0.5)
        result = sizer.calc(
            "000001", score=80, macro_cap=0.80,
            position_limits={"single_stock_cap": 0.20},
        )
        # base = (80-50)/50 × 0.80 = 0.48, capped at 0.20
        assert result.target_weight == 0.20

    # ------------------------------------------------------------------
    # 负期望测试
    # ------------------------------------------------------------------

    def test_negative_expectation(self, empty_tracker: TradeTracker):
        """负期望: n>=5 但 f*≤0 → method="negative_expectation"。"""
        # 手动创建 KellyParams 绕过 tracker
        sizer = KellyPositionSizer(empty_tracker)
        kp = KellyParams(
            symbol="600519", win_rate=0.2, payoff_ratio=0.5,
            n_trades=10, kelly_f=0.0,  # b×p-q = 0.5×0.2-0.8 = -0.7 < 0
        )
        result = sizer.calc_with_params(kp, score=70, macro_cap=0.80)

        assert result.method == "negative_expectation"
        assert result.target_weight == 0.0

    # ------------------------------------------------------------------
    # calc_with_params 测试
    # ------------------------------------------------------------------

    def test_calc_with_params_hot(self):
        """直接使用 KellyParams 计算（跳过 tracker）。"""
        sizer = KellyPositionSizer(TradeTracker())
        kp = KellyParams(
            symbol="600519", win_rate=0.6, payoff_ratio=2.0,
            n_trades=5, kelly_f=0.4,
        )
        result = sizer.calc_with_params(kp, score=70, macro_cap=0.80)
        assert result.method == "kelly"
        assert result.target_weight == pytest.approx(0.20)

    def test_calc_with_params_cold(self):
        """KellyParams 冷启动 (n<5) → 线性回退。"""
        sizer = KellyPositionSizer(TradeTracker())
        kp = KellyParams(
            symbol="000001", win_rate=0.5, payoff_ratio=1.0,
            n_trades=3, kelly_f=0.0,
        )
        result = sizer.calc_with_params(kp, score=70, macro_cap=0.80)
        assert result.method == "linear_fallback"

    # ------------------------------------------------------------------
    # Kelly 分数边界测试
    # ------------------------------------------------------------------

    def test_kelly_fraction_clamped(self, hot_tracker: TradeTracker):
        """kelly_fraction 自动裁剪到 [0.1, 1.0]。"""
        sizer = KellyPositionSizer(hot_tracker, default_kelly_fraction=0.5)

        # fraction=0.05 → clamp 到 0.1
        result = sizer.calc("600519", score=70, macro_cap=0.80, kelly_fraction=0.05)
        assert result.kelly_fraction == 0.1
        assert result.target_weight == pytest.approx(0.04)  # 0.1 × 0.4

        # fraction=1.5 → clamp 到 1.0
        result = sizer.calc("600519", score=70, macro_cap=0.80, kelly_fraction=1.5)
        assert result.kelly_fraction == 1.0
        assert result.target_weight == pytest.approx(0.40)

    # ------------------------------------------------------------------
    # source_citation 测试
    # ------------------------------------------------------------------

    def test_source_citation_kelly(self, hot_tracker: TradeTracker):
        """热启动 source_citation 含凯利参数。"""
        sizer = KellyPositionSizer(hot_tracker)
        result = sizer.calc("600519", score=70, macro_cap=0.80)
        assert "kelly" in result.source_citation
        assert "b=" in result.source_citation
        assert "p=" in result.source_citation
        assert "n=" in result.source_citation

    def test_source_citation_linear(self, cold_tracker: TradeTracker):
        """冷启动 source_citation 含回退原因。"""
        sizer = KellyPositionSizer(cold_tracker)
        result = sizer.calc("000001", score=70, macro_cap=0.80)
        assert "linear_fallback" in result.source_citation
        assert "n=" in result.source_citation
