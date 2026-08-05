# -*- coding: utf-8 -*-
"""模拟交易模块单元测试。"""

import pytest

from src.paper_trading.bridge import (
    PaperTradeResult,
    PaperTradingBridge,
    PaperTradingSession,
)
from src.paper_trading.signal_adapter import MoniOrder, SignalAdapter


class TestSignalAdapter:
    """SignalAdapter 测试。"""

    def test_default_construction(self):
        adapter = SignalAdapter()
        assert adapter is not None
        assert adapter._capital == 100_000.0

    def test_custom_capital(self):
        adapter = SignalAdapter(initial_capital=500_000.0)
        assert adapter._capital == 500_000.0

    def test_quantity_calculation_basic(self):
        """基本数量计算: 5% 仓位 = 5000 元 = 50 股 (10元/股) → 取整到 0 (不足100股)。"""
        adapter = SignalAdapter(initial_capital=100_000.0)

        class FakeSignal:
            symbol = "600519"
            action = "buy"
            weight = 0.05
            score = 75.0
            reason = "test"
            limit_price = None

        order = adapter.to_moni_order(FakeSignal(), current_price=10.0)
        # 5000 / 10 = 500 → 取整到 500
        assert order is not None
        assert order.symbol == "600519"
        assert order.action == "buy"
        assert order.quantity >= 100  # At least 1 lot

    def test_quantity_calculation_small_position(self):
        """极小仓位 (<2000元) 跳过。"""
        adapter = SignalAdapter(initial_capital=10_000.0)

        class FakeSignal:
            symbol = "000001"
            action = "buy"
            weight = 0.01  # 100元
            score = 50.0
            reason = "test"
            limit_price = None

        order = adapter.to_moni_order(FakeSignal(), current_price=50.0)
        assert order is None  # 低于最低下单金额

    def test_deduplication(self):
        """信号去重 — 同一天同股同方向只执行一次。"""
        adapter = SignalAdapter()

        class FakeSignal:
            symbol = "600519"
            action = "buy"
            weight = 0.10
            score = 80.0
            reason = "test"
            limit_price = None

        order1 = adapter.to_moni_order(FakeSignal(), current_price=100.0)
        order2 = adapter.to_moni_order(FakeSignal(), current_price=100.0)
        assert order1 is not None
        assert order2 is None  # 重复信号被跳过

    def test_batch_conversion(self):
        """批量信号转换按权重排序。"""
        adapter = SignalAdapter(initial_capital=1_000_000.0)

        class FakeSignal:
            def __init__(self, sym, weight):
                self.symbol = sym
                self.action = "buy"
                self.weight = weight
                self.score = 80.0
                self.reason = "test"
                self.limit_price = None

        signals = [
            FakeSignal("000001", 0.05),
            FakeSignal("600519", 0.15),
            FakeSignal("000002", 0.10),
        ]
        orders = adapter.to_moni_orders(signals, {"000001": 10.0, "600519": 100.0, "000002": 20.0})
        assert len(orders) >= 2
        # 按权重降序：600519(0.15) → 000002(0.10) → 000001(0.05)
        if len(orders) == 3:
            assert orders[0].symbol == "600519"


class TestPaperTradingBridge:
    """PaperTradingBridge 测试。"""

    def test_default_construction(self):
        bridge = PaperTradingBridge()
        assert bridge is not None
        assert bridge._capital == 100_000.0

    def test_custom_capital(self):
        bridge = PaperTradingBridge(capital=500_000.0)
        assert bridge._capital == 500_000.0

    def test_execute_dry_run(self):
        """干运行不实际下单。"""
        bridge = PaperTradingBridge()

        class FakeSignal:
            symbol = "600519"
            name = "贵州茅台"
            action = "buy"
            weight = 0.10
            score = 80.0
            reason = "测试买入"
            limit_price = None

        result = bridge.execute_signal(FakeSignal(), current_price=100.0, dry_run=True)
        assert result is not None
        assert result.symbol == "600519"
        assert result.status == "submitted"
        assert "DRY_RUN" in result.order_id

    def test_report_no_results(self):
        bridge = PaperTradingBridge()
        report = bridge.report()
        assert "📭" in report

    def test_report_with_results(self):
        bridge = PaperTradingBridge()
        bridge._results = [
            PaperTradeResult(symbol="600519", action="buy", status="submitted", order_id="ORD001", price=100.0, quantity=100),
            PaperTradeResult(symbol="000001", action="sell", status="rejected", message="资金不足"),
            PaperTradeResult(symbol="000002", action="buy", status="error", message="API 超时"),
        ]
        report = bridge.report()
        assert "600519" in report
        assert "000001" in report
        assert "资金不足" in report or "rejected" in report.lower()
        assert "API 超时" in report or "error" in report.lower()

    def test_feed_to_learner(self):
        bridge = PaperTradingBridge()
        bridge._results = [
            PaperTradeResult(symbol="600519", action="buy", status="submitted", order_id="ORD001"),
            PaperTradeResult(symbol="000001", action="buy", status="skipped", message="已处理"),
        ]
        feedbacks = bridge.feed_to_learner()
        assert len(feedbacks) == 1  # skipped 被过滤
        assert feedbacks[0]["symbol"] == "600519"
        assert feedbacks[0]["order_id"] == "ORD001"

    def test_clear_results(self):
        bridge = PaperTradingBridge()
        bridge._results = [PaperTradeResult(symbol="test", action="buy", status="submitted")]
        bridge.clear_results()
        assert len(bridge._results) == 0


class TestPaperTradeResult:
    """PaperTradeResult dataclass 测试。"""

    def test_default_values(self):
        result = PaperTradeResult(symbol="test", action="buy")
        assert result.symbol == "test"
        assert result.action == "buy"
        assert result.order_id == ""
        assert result.status == "unknown"


class TestPaperTradingSession:
    """PaperTradingSession dataclass 测试。"""

    def test_default_values(self):
        session = PaperTradingSession()
        assert session.initial_capital == 100_000.0
        assert session.total_assets == 0.0
        assert session.pos_count == 0


class TestMoniOrder:
    """MoniOrder dataclass 测试。"""

    def test_default_values(self):
        order = MoniOrder(symbol="600519")
        assert order.symbol == "600519"
        assert order.action == "buy"
        assert order.use_market_price is True


class TestEventReview:
    """P2-3 事件驱动复盘触发频率：仅亏损平仓 / 连续止损 / 回撤超标触发。"""

    @pytest.fixture
    def engine(self, tmp_path):
        from src.paper_trading.engine import PaperTradingEngine

        eng = PaperTradingEngine(data_dir=tmp_path)
        eng._triggered = []
        eng._trigger_event_review = (
            lambda state, reasons, trades: eng._triggered.append(reasons)
        )
        return eng

    @staticmethod
    def _state(drawdown: float = 0.01):
        from src.paper_trading.state import PortfolioState

        hwm = 1000.0
        return PortfolioState(
            initial_capital=1000.0,
            high_water_mark=hwm,
            cash=hwm * (1 - drawdown),
        )

    @staticmethod
    def _trade(symbol: str = "600519", action: str = "sell", pnl_pct: float = 0.0):
        from src.paper_trading.state import PaperTrade

        return PaperTrade(
            trade_id=f"{symbol}_{action}_{pnl_pct}",
            symbol=symbol,
            name="测试",
            action=action,
            price=10.0,
            quantity=100,
            notional=1000.0,
            commission=1.0,
            stamp_tax=0.0,
            transfer_fee=0.0,
            total_cost=1.0,
            net_amount=999.0,
            reason="test",
            timestamp="2026-08-06T10:00:00",
            remaining_cash=1000.0,
            pnl_pct=pnl_pct,
        )

    def test_profit_sell_does_not_trigger(self, engine, monkeypatch):
        """正常止盈平仓不触发单笔事件复盘。"""
        monkeypatch.setattr(engine._state_mgr, "load_trades", lambda limit=30: [])
        engine._maybe_trigger_event_review(self._state(), [self._trade(pnl_pct=0.05)])
        assert engine._triggered == []

    def test_loss_sell_triggers(self, engine, monkeypatch):
        """亏损平仓触发单笔事件复盘。"""
        monkeypatch.setattr(engine._state_mgr, "load_trades", lambda limit=30: [])
        engine._maybe_trigger_event_review(self._state(), [self._trade(pnl_pct=-0.03)])
        assert len(engine._triggered) == 1
        assert any("亏损平仓" in r for r in engine._triggered[0])

    def test_mixed_sells_only_loss_counts(self, engine, monkeypatch):
        """同日多笔卖出：仅亏损笔数计入，止盈笔不计入。"""
        monkeypatch.setattr(engine._state_mgr, "load_trades", lambda limit=30: [])
        trades = [
            self._trade("000001", "sell", 0.08),   # 止盈
            self._trade("600519", "sell", -0.02),  # 亏损
        ]
        engine._maybe_trigger_event_review(self._state(), trades)
        assert len(engine._triggered) == 1
        assert any("亏损平仓 1 笔" in r for r in engine._triggered[0])

    def test_consecutive_losses_triggers(self, engine, monkeypatch):
        """连续 ≥3 笔亏损卖出触发止损复盘（保留既有行为）。"""
        monkeypatch.setattr(
            engine._state_mgr,
            "load_trades",
            lambda limit=30: [
                self._trade(symbol=f"6{i}", pnl_pct=-0.02) for i in range(3)
            ],
        )
        engine._maybe_trigger_event_review(self._state(), [])
        assert len(engine._triggered) == 1
        assert any("连续" in r for r in engine._triggered[0])

    def test_drawdown_triggers(self, engine, monkeypatch):
        """回撤 ≥8% 触发即时复盘（保留既有行为）。"""
        monkeypatch.setattr(engine._state_mgr, "load_trades", lambda limit=30: [])
        engine._maybe_trigger_event_review(self._state(drawdown=0.09), [])
        assert len(engine._triggered) == 1
        assert any("回撤" in r for r in engine._triggered[0])

    def test_no_trigger_when_clean(self, engine, monkeypatch):
        """无亏损平仓/连亏/回撤 → 不触发复盘。"""
        monkeypatch.setattr(engine._state_mgr, "load_trades", lambda limit=30: [])
        engine._maybe_trigger_event_review(self._state(), [])
        assert engine._triggered == []
