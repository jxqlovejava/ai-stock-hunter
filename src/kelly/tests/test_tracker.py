# -*- coding: utf-8 -*-
"""TradeTracker 测试 — 交易记录 CRUD + p/b 计算。"""

import json
import tempfile
from pathlib import Path

import pytest

from src.kelly.tracker import DEFAULT_TRADES_PATH, KellyParams, TradeRecord, TradeTracker


class TestTradeRecord:
    """TradeRecord 数据类测试。"""

    def test_long_win(self):
        r = TradeRecord(
            symbol="600519", entry_date="2026-01-15", exit_date="2026-03-20",
            entry_price=100.0, exit_price=110.0, direction="LONG",
        )
        assert r.is_win is True
        assert r.is_loss is False
        assert r.return_pct == pytest.approx(0.10)

    def test_long_loss(self):
        r = TradeRecord(
            symbol="600519", entry_date="2026-01-15", exit_date="2026-03-20",
            entry_price=100.0, exit_price=95.0, direction="LONG",
        )
        assert r.is_win is False
        assert r.is_loss is True
        assert r.return_pct == pytest.approx(-0.05)

    def test_short_win(self):
        r = TradeRecord(
            symbol="000001", entry_date="2026-01-15", exit_date="2026-01-20",
            entry_price=100.0, exit_price=90.0, direction="SHORT",
        )
        assert r.is_win is True
        assert r.return_pct == pytest.approx(0.10)

    def test_short_loss(self):
        r = TradeRecord(
            symbol="000001", entry_date="2026-01-15", exit_date="2026-01-20",
            entry_price=100.0, exit_price=110.0, direction="SHORT",
        )
        assert r.is_win is False
        assert r.is_loss is True
        assert r.return_pct == pytest.approx(-0.10)

    def test_zero_entry_price(self):
        r = TradeRecord(
            symbol="000001", entry_date="2026-01-15", exit_date="2026-01-20",
            entry_price=0.0, exit_price=100.0,
        )
        assert r.return_pct == 0.0

    def test_serialization_roundtrip(self):
        r = TradeRecord(
            symbol="600519", entry_date="2026-01-15", exit_date="2026-03-20",
            entry_price=1800.0, exit_price=1950.0, shares=100,
            direction="LONG", notes="测试茅台",
        )
        d = r.to_dict()
        r2 = TradeRecord.from_dict(d)
        assert r2.symbol == r.symbol
        assert r2.entry_price == r.entry_price
        assert r2.exit_price == r.exit_price
        assert r2.shares == r.shares
        assert r2.direction == r.direction
        assert r2.notes == r.notes


class TestKellyParams:
    """KellyParams 数据类测试。"""

    def test_is_hot_enough_trades(self):
        kp = KellyParams(symbol="600519", win_rate=0.6, payoff_ratio=2.0,
                         n_trades=5, kelly_f=0.35)
        assert kp.is_hot is True

    def test_is_not_hot_few_trades(self):
        kp = KellyParams(symbol="600519", win_rate=0.6, payoff_ratio=2.0,
                         n_trades=4, kelly_f=0.0)
        assert kp.is_hot is False

    def test_is_not_hot_zero_payoff(self):
        kp = KellyParams(symbol="600519", win_rate=0.6, payoff_ratio=0.0,
                         n_trades=10, kelly_f=0.0)
        assert kp.is_hot is False

    def test_is_not_hot_empty(self):
        kp = KellyParams(symbol="600519")
        assert kp.is_hot is False


class TestTradeTracker:
    """TradeTracker CRUD + 持久化测试。"""

    @pytest.fixture
    def tmp_path(self):
        with tempfile.TemporaryDirectory() as d:
            yield Path(d) / "trades.json"

    @pytest.fixture
    def tracker(self, tmp_path):
        return TradeTracker(path=tmp_path)

    def test_track_and_get(self, tracker: TradeTracker, tmp_path):
        tracker.track(TradeRecord(
            symbol="600519", entry_date="2026-01-15", exit_date="2026-03-20",
            entry_price=100.0, exit_price=110.0,
        ))
        trades = tracker.get_trades("600519")
        assert len(trades) == 1
        assert trades[0].symbol == "600519"
        assert trades[0].is_win is True

        # 验证持久化
        assert tmp_path.exists()
        data = json.loads(tmp_path.read_text())
        assert "600519" in data
        assert len(data["600519"]) == 1

    def test_get_all_symbols(self, tracker: TradeTracker):
        tracker.track(TradeRecord(
            symbol="600519", entry_date="2026-01-15", exit_date="2026-01-20",
            entry_price=100.0, exit_price=110.0,
        ))
        tracker.track(TradeRecord(
            symbol="000001", entry_date="2026-02-01", exit_date="2026-02-10",
            entry_price=50.0, exit_price=45.0,
        ))
        symbols = tracker.get_all_symbols()
        assert sorted(symbols) == ["000001", "600519"]

    def test_remove_trade(self, tracker: TradeTracker):
        tracker.track(TradeRecord(
            symbol="600519", entry_date="2026-01-15", exit_date="2026-01-20",
            entry_price=100.0, exit_price=110.0,
        ))
        tracker.track(TradeRecord(
            symbol="600519", entry_date="2026-02-01", exit_date="2026-02-10",
            entry_price=105.0, exit_price=95.0,
        ))
        assert len(tracker.get_trades("600519")) == 2

        # 删除第 0 笔
        assert tracker.remove_trade("600519", 0) is True
        assert len(tracker.get_trades("600519")) == 1

        # 越界删除
        assert tracker.remove_trade("600519", 5) is False

    def test_clear_symbol(self, tracker: TradeTracker):
        tracker.track(TradeRecord(
            symbol="600519", entry_date="2026-01-15", exit_date="2026-01-20",
            entry_price=100.0, exit_price=110.0,
        ))
        tracker.clear_symbol("600519")
        assert len(tracker.get_trades("600519")) == 0
        assert "600519" not in tracker.get_all_symbols()

    def test_persistence_across_instances(self, tmp_path):
        t1 = TradeTracker(path=tmp_path)
        t1.track(TradeRecord(
            symbol="600519", entry_date="2026-01-15", exit_date="2026-03-20",
            entry_price=100.0, exit_price=110.0,
        ))

        t2 = TradeTracker(path=tmp_path)
        assert "600519" in t2.get_all_symbols()
        assert len(t2.get_trades("600519")) == 1

    # ------------------------------------------------------------------
    # 凯利参数计算测试
    # ------------------------------------------------------------------

    def test_kelly_params_all_wins(self, tracker: TradeTracker):
        """5 笔全赢: p=1.0, b 取决于 avg_win。"""
        for i in range(5):
            tracker.track(TradeRecord(
                symbol="600519", entry_date="2026-01-15", exit_date="2026-01-20",
                entry_price=100.0, exit_price=110.0,
            ))
        kp = tracker.get_kelly_params("600519")
        assert kp.n_trades == 5
        assert kp.win_rate == 1.0
        assert kp.is_hot is False  # 全赢 → 无亏损 → avg_loss=0 → b=0

    def test_kelly_params_mixed(self, tracker: TradeTracker):
        """3 赢 2 亏: p=0.6, b 可计算。"""
        # 3 wins
        for _ in range(3):
            tracker.track(TradeRecord(
                symbol="600519", entry_date="2026-01-15", exit_date="2026-01-20",
                entry_price=100.0, exit_price=110.0,  # +10%
            ))
        # 2 losses
        for _ in range(2):
            tracker.track(TradeRecord(
                symbol="600519", entry_date="2026-02-01", exit_date="2026-02-10",
                entry_price=100.0, exit_price=95.0,  # -5%
            ))

        kp = tracker.get_kelly_params("600519")
        assert kp.n_trades == 5
        assert kp.win_rate == 0.6
        assert kp.payoff_ratio == pytest.approx(2.0)  # 10% / 5% = 2.0
        assert kp.is_hot is True
        # f* = (2.0 × 0.6 - 0.4) / 2.0 = (1.2 - 0.4)/2 = 0.4
        assert kp.kelly_f == pytest.approx(0.4)

    def test_kelly_params_all_loss(self, tracker: TradeTracker):
        """5 笔全亏: p=0.0 → f* = 0（负期望）。"""
        for i in range(5):
            tracker.track(TradeRecord(
                symbol="600519", entry_date="2026-01-15", exit_date="2026-01-20",
                entry_price=100.0, exit_price=95.0,
            ))
        kp = tracker.get_kelly_params("600519")
        assert kp.n_trades == 5
        assert kp.win_rate == 0.0
        assert kp.kelly_f == 0.0
        assert kp.is_hot is False  # 全亏 → 无 win → avg_win=0 → b=0

    def test_kelly_params_negative_expectation(self, tracker: TradeTracker):
        """b × p - q < 0 → f* = 0。"""
        # 2 wins at 5%, 8 losses at 10%: b=0.5, p=0.2
        for _ in range(2):
            tracker.track(TradeRecord(
                symbol="000001", entry_date="2026-01-15", exit_date="2026-01-20",
                entry_price=100.0, exit_price=105.0,
            ))
        for _ in range(8):
            tracker.track(TradeRecord(
                symbol="000001", entry_date="2026-01-15", exit_date="2026-01-20",
                entry_price=100.0, exit_price=90.0,
            ))
        kp = tracker.get_kelly_params("000001")
        # b = 5% / 10% = 0.5, p = 0.2
        # b×p - q = 0.5×0.2 - 0.8 = 0.1 - 0.8 = -0.7 < 0
        assert kp.kelly_f == 0.0

    def test_kelly_params_cold_start(self, tracker: TradeTracker):
        """无交易记录 → 冷启动。"""
        kp = tracker.get_kelly_params("000001")
        assert kp.n_trades == 0
        assert kp.win_rate == 0.0
        assert kp.payoff_ratio == 0.0
        assert kp.kelly_f == 0.0
        assert kp.is_hot is False

    def test_get_all_kelly_params(self, tracker: TradeTracker):
        for i in range(5):
            tracker.track(TradeRecord(
                symbol="600519", entry_date="2026-01-15", exit_date="2026-01-20",
                entry_price=100.0, exit_price=110.0,
            ))
        for i in range(5):
            tracker.track(TradeRecord(
                symbol="000001", entry_date="2026-01-15", exit_date="2026-01-20",
                entry_price=50.0, exit_price=52.5,
            ))
        all_params = tracker.get_all_kelly_params()
        assert len(all_params) == 2
        assert "600519" in all_params
        assert "000001" in all_params

    def test_summary_output(self, tracker: TradeTracker):
        for i in range(5):
            tracker.track(TradeRecord(
                symbol="600519", entry_date="2026-01-15", exit_date="2026-01-20",
                entry_price=100.0, exit_price=110.0,
            ))
        for i in range(5):
            tracker.track(TradeRecord(
                symbol="000001", entry_date="2026-01-15", exit_date="2026-01-20",
                entry_price=50.0, exit_price=45.0,
            ))
        s = tracker.summary()
        assert "600519" in s
        assert "000001" in s
