# -*- coding: utf-8 -*-
"""回测 & 博弈论模块测试。"""

from __future__ import annotations

import pytest


class TestGameTheory:
    def test_rules_loaded(self):
        from src.game_theory.rules import A_SHARE_RULES
        assert len(A_SHARE_RULES) >= 15

    def test_top3_rules(self):
        from src.game_theory.rules import TOP_3_RULES
        assert len(TOP_3_RULES) == 3
        for m in TOP_3_RULES:
            assert len(m.causal_chain) >= 2
            assert len(m.leading_indicators) >= 2

    def test_all_rules_have_fields(self):
        from src.game_theory.rules import A_SHARE_RULES
        for r in A_SHARE_RULES:
            assert r.id, f"Rule {r.name} missing id"
            assert r.name
            assert r.formal_def
            assert r.design_intent
            assert len(r.who_benefits) >= 1
            assert r.behavioral_incentive
            assert r.large_vs_small_asymmetry

    def test_summary(self):
        from src.game_theory import get_game_theory_summary
        s = get_game_theory_summary()
        assert "15 条核心规则" in s or "A_SHARE_RULES" in s or "15" in s
        assert "资金流因果" in s or "TOP_3_RULES" in s or "核心玩家" in s

    def test_evidence_levels(self):
        from src.game_theory.rules import A_SHARE_RULES, EvidenceLevel
        verified = sum(1 for r in A_SHARE_RULES if r.evidence == EvidenceLevel.VERIFIED)
        assert verified > 0, "至少应有一条 VERIFIED 级别的规则"


class TestBacktestEngine:
    def test_engine_creation(self):
        from src.backtest.engine import BacktestEngine
        engine = BacktestEngine(initial_cash=100000)
        assert engine._initial_cash == 100000

    def test_engine_requires_strategy(self):
        from src.backtest.engine import BacktestEngine
        engine = BacktestEngine()
        with pytest.raises(RuntimeError, match="未注册策略"):
            engine.run()

    def test_commission(self):
        from src.backtest.engine import AShareCommission
        comm = AShareCommission()
        # 买入: 佣金 + 滑点
        buy_cost = comm._getcommission(100, 10.0, True)
        # 卖出: 佣金 + 滑点 + 印花税
        sell_cost = comm._getcommission(-100, 10.0, True)
        # 卖出成本 > 买入成本（因为多印花税）
        assert sell_cost > buy_cost
        # 买入成本 > 0
        assert buy_cost > 0

    def test_backtest_result(self):
        from src.backtest.engine import BacktestResult
        r = BacktestResult(
            strategy_name="MVP1",
            start_date="2015-01-01",
            end_date="2024-12-31",
            initial_cash=1000000,
            final_value=1500000,
            total_return=0.5,
            annual_return=0.05,
            sharpe_ratio=0.8,
            max_drawdown=-0.25,
            win_rate=0.55,
            total_trades=200,
        )
        assert r.total_return == 0.5
        assert r.sharpe_ratio == 0.8

    def test_year_diff(self):
        from src.backtest.engine import BacktestEngine
        years = BacktestEngine._year_diff("2015-01-01", "2024-12-31")
        assert 9.9 <= years <= 10.1  # ~10 years

    def test_win_rate(self):
        from src.backtest.engine import BacktestEngine
        assert BacktestEngine._win_rate({}) == 0.0
        trades = {"won": {"total": 60}, "lost": {"total": 40}}
        assert BacktestEngine._win_rate(trades) == 0.6
