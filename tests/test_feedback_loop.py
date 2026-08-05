# -*- coding: utf-8 -*-
"""P2-1/P2-2/P2-3 测试：错误分类 + 反馈采集闭环 + 事件驱动复盘。

覆盖:
  ① MistakeType 七类 + Feedback 默认值向后兼容
  ② feedback add CLI 可写 feedback.json（tmp_path 隔离）
  ③ 复盘事件触发（平仓 / 连亏 / 回撤超标）
  ④ deviation_reason → MistakeType 映射
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# ① MistakeType 七类 + Feedback 默认值向后兼容
# ---------------------------------------------------------------------------


class TestMistakeType:
    def test_seven_categories(self):
        from src.learner.feedback import MistakeType
        expected = {
            "none",
            "chased_move",
            "ignored_news_conflict",
            "stop_too_tight",
            "stop_too_wide",
            "overleveraged",
            "held_too_long",
        }
        assert {m.value for m in MistakeType} == expected
        assert len(list(MistakeType)) == 7

    def test_feedback_default_mistake_type_backward_compat(self):
        """新增字段默认 NONE，不破坏既有构造方式。"""
        from src.learner.feedback import Feedback, FeedbackType, MistakeType
        fb = Feedback("FB_000001", "SIG_1", type=FeedbackType.AGREE)
        assert fb.mistake_type == MistakeType.NONE
        assert fb.symbol == ""
        assert fb.result == ""

    def test_mistake_type_unknown_value_falls_back(self):
        """旧数据未知值回退 NONE（向后兼容）。"""
        from src.learner.feedback import MistakeType
        assert MistakeType("garbage_not_exist") == MistakeType.NONE

    def test_mistake_type_roundtrip_persistence(self, tmp_path):
        """mistake_type 落盘并重新加载后保持一致。"""
        from src.learner.feedback import FeedbackCollector, MistakeType
        path = tmp_path / "feedback.json"
        c1 = FeedbackCollector(db_path=str(path))
        c1.record_trade_result(
            symbol="600519", direction="SELL", result="loss",
            mistake_type=MistakeType.OVERLEVERAGED,
            lesson="满仓加杠杆遇到利空公告，未设止损",
            actual_return=-0.12,
        )
        c2 = FeedbackCollector(db_path=str(path))
        fb = c2.get_by_signal("TRADE_600519")[0]
        assert fb.mistake_type == MistakeType.OVERLEVERAGED
        assert fb.symbol == "600519"
        assert fb.result == "loss"


# ---------------------------------------------------------------------------
# ④ deviation_reason → MistakeType 映射
# ---------------------------------------------------------------------------


class TestDeviationMapping:
    def test_maps_each_category(self):
        from src.backtest.review import mistake_type_from_deviation
        from src.learner.feedback import MistakeType
        cases = {
            "高位追涨被套": MistakeType.CHASED_MOVE,
            "忽视利空公告强行买入": MistakeType.IGNORED_NEWS_CONFLICT,
            "止损过紧被洗盘震出": MistakeType.STOP_TOO_TIGHT,
            "止损太宽扛单亏损扩大": MistakeType.STOP_TOO_WIDE,
            "满仓加杠杆爆仓": MistakeType.OVERLEVERAGED,
            "持仓过久利润回吐": MistakeType.HELD_TOO_LONG,
            "正常卖出": MistakeType.NONE,
            "": MistakeType.NONE,
            None: MistakeType.NONE,
        }
        for text, expected in cases.items():
            assert mistake_type_from_deviation(text or "") == expected, text

    def test_mistake_type_from_review_uses_field_first(self):
        from src.backtest.review import mistake_type_from_review, TradeReview
        r = TradeReview(symbol="600519", deviation_reason="高位追涨", mistake_type="stop_too_tight")
        assert mistake_type_from_review(r).value == "stop_too_tight"

    def test_mistake_type_from_review_falls_back_to_reason(self):
        from src.backtest.review import mistake_type_from_review, TradeReview
        r = TradeReview(symbol="600519", deviation_reason="高位追涨被套", mistake_type="")
        assert mistake_type_from_review(r).value == "chased_move"

    def test_review_roundtrip_preserves_mistake_type(self, tmp_path):
        from src.backtest.review import TradeReview, TradeReviewer
        reviewer = TradeReviewer(storage_dir=tmp_path)
        r = TradeReview(
            symbol="600519", deviation_reason="止损过紧被洗",
            mistake_type="stop_too_tight", return_pct=-0.05,
        )
        rid = reviewer.record(r)
        loaded = reviewer.load_all()[0]
        assert loaded.mistake_type == "stop_too_tight"
        assert loaded.deviation_reason == "止损过紧被洗"

    def test_stats_counts_mistake_categories(self, tmp_path):
        from src.backtest.review import TradeReview, TradeReviewer
        reviewer = TradeReviewer(storage_dir=tmp_path)
        reviewer.record(TradeReview(symbol="600519", deviation_reason="高位追涨", return_pct=-0.05))
        reviewer.record(TradeReview(symbol="000001", deviation_reason="止损过紧", return_pct=-0.03))
        reviewer.record(TradeReview(symbol="000002", deviation_reason="满仓杠杆", return_pct=-0.08))
        stats = reviewer.stats()
        assert stats.mistake_categories.get("chased_move") == 1
        assert stats.mistake_categories.get("stop_too_tight") == 1
        assert stats.mistake_categories.get("overleveraged") == 1


class TestLessonSpecificity:
    def test_rejects_vague_lessons(self):
        from src.learner.feedback import validate_lesson_specificity
        for vague in ["操作失误", "行情不好", "心态不好", "运气不好"]:
            ok, _msg = validate_lesson_specificity(vague)
            assert not ok, vague

    def test_accepts_specific_lesson(self):
        from src.learner.feedback import validate_lesson_specificity
        ok, _msg = validate_lesson_specificity("突破假信号追高被套，未等回踩确认就冲进去")
        assert ok

    def test_rejects_empty(self):
        from src.learner.feedback import validate_lesson_specificity
        assert not validate_lesson_specificity("")[0]


# ---------------------------------------------------------------------------
# ② feedback add CLI 可写 feedback.json（tmp_path 隔离）
# ---------------------------------------------------------------------------


class TestFeedbackAddCli:
    def _run_cli(self, monkeypatch, db_path, inputs):
        import builtins
        it = iter(inputs)
        monkeypatch.setattr(builtins, "input", lambda prompt="": next(it))
        monkeypatch.setenv("BAIZE_FEEDBACK_PATH", str(db_path))
        from src.cli import cmd_feedback
        cmd_feedback(["add"])

    def test_add_writes_feedback_json(self, tmp_path, monkeypatch, capsys):
        db_path = tmp_path / "feedback.json"
        self._run_cli(
            monkeypatch, db_path,
            [
                "600519",   # 标的
                "SELL",     # 方向
                "loss",     # 结果
                "1",        # 错误类型: chased_move
                "-8.5",     # 实际收益率%
                "突破假信号追高被套，未等回踩确认",  # 教训
            ],
        )
        assert db_path.exists()
        data = json.loads(db_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        entry = data[0]
        assert entry["symbol"] == "600519"
        assert entry["user_action"] == "SELL"
        assert entry["result"] == "loss"
        assert entry["mistake_type"] == "chased_move"
        assert entry["actual_return"] == pytest.approx(-0.085)
        assert "追高" in entry["lesson"]
        out = capsys.readouterr().out
        assert "反馈已记录" in out

    def test_add_rejects_vague_lesson_no_write(self, tmp_path, monkeypatch, capsys):
        """空话教训被拒，不写文件。"""
        db_path = tmp_path / "feedback.json"
        self._run_cli(
            monkeypatch, db_path,
            ["600519", "SELL", "loss", "0", "", "操作失误"],
        )
        assert not db_path.exists() or json.loads(db_path.read_text()) == []
        out = capsys.readouterr().out
        assert "空泛" in out

    def test_summary_prints_mistake_types(self, tmp_path, monkeypatch, capsys):
        from src.learner.feedback import FeedbackCollector, MistakeType
        db_path = tmp_path / "feedback.json"
        c = FeedbackCollector(db_path=str(db_path))
        c.record_trade_result(symbol="600519", direction="SELL", result="loss",
                              mistake_type=MistakeType.STOP_TOO_TIGHT,
                              lesson="止损过紧被洗盘震出，应参考波动率设止损",
                              actual_return=-0.05)
        monkeypatch.setenv("BAIZE_FEEDBACK_PATH", str(db_path))
        from src.cli import cmd_feedback
        cmd_feedback(["summary"])
        out = capsys.readouterr().out
        assert "stop_too_tight" in out
        assert "止损过紧" in out


# ---------------------------------------------------------------------------
# ③ 复盘事件触发（平仓 / 连亏 / 回撤超标）
# ---------------------------------------------------------------------------


def _make_engine(tmp_path):
    from src.paper_trading.engine import PaperTradingEngine
    return PaperTradingEngine(
        capital=200_000,
        data_dir=tmp_path / "pt",
        feedback_path=str(tmp_path / "feedback.json"),
        journal_path=str(tmp_path / "journal.db"),
    )


def _sell_trade(symbol="600519", pnl_pct=-0.05, reason="止损"):
    from src.paper_trading.state import PaperTrade
    return PaperTrade(
        trade_id=f"{symbol}_sell", symbol=symbol, name="测试股", action="sell",
        price=10.0, quantity=100, notional=1000.0,
        commission=1.0, stamp_tax=0.5, transfer_fee=0.0, total_cost=1.5,
        net_amount=998.5, reason=reason, timestamp="2026-08-05T10:00:00",
        remaining_cash=90000.0, pnl_pct=pnl_pct,
    )


class TestEventReviewTrigger:
    def test_sell_closure_triggers(self, tmp_path):
        from src.paper_trading.state import PortfolioState
        engine = _make_engine(tmp_path)
        triggered = []
        engine._trigger_event_review = lambda state, reasons, trades: triggered.append(reasons)
        engine._maybe_trigger_event_review(
            PortfolioState.initial(200_000), [_sell_trade()],
        )
        assert triggered, "平仓事件应触发即时复盘"
        assert any("平仓" in r for reasons in triggered for r in reasons)

    def test_consecutive_losses_trigger(self, tmp_path):
        from src.paper_trading.state import PortfolioState
        engine = _make_engine(tmp_path)
        # 写 3 笔连续亏损卖出
        mgr = engine._state_mgr
        for i in range(3):
            mgr.append_trade(_sell_trade(symbol=f"60000{i}", pnl_pct=-0.05))
        assert engine._count_consecutive_losses() == 3
        triggered = []
        engine._trigger_event_review = lambda state, reasons, trades: triggered.append(reasons)
        engine._maybe_trigger_event_review(PortfolioState.initial(200_000), [])
        assert triggered, "连续亏损应触发即时复盘"
        assert any("连续" in r for reasons in triggered for r in reasons)

    def test_drawdown_threshold_trigger(self, tmp_path):
        from dataclasses import replace
        from src.paper_trading.state import PortfolioState
        engine = _make_engine(tmp_path)
        state = PortfolioState.initial(200_000)
        state = replace(state, high_water_mark=200_000, cash=180_000)  # 回撤 10%
        assert state.drawdown_pct >= engine.EVENT_REVIEW_DRAWDOWN
        triggered = []
        engine._trigger_event_review = lambda state, reasons, trades: triggered.append(reasons)
        engine._maybe_trigger_event_review(state, [])
        assert triggered, "回撤超标应触发即时复盘"
        assert any("回撤" in r for reasons in triggered for r in reasons)

    def test_no_trigger_when_quiet(self, tmp_path):
        from src.paper_trading.state import PortfolioState
        engine = _make_engine(tmp_path)
        triggered = []
        engine._trigger_event_review = lambda state, reasons, trades: triggered.append(reasons)
        engine._maybe_trigger_event_review(PortfolioState.initial(200_000), [])
        assert not triggered, "无平仓/连亏/回撤时不应触发"

    def test_event_review_generates_report_and_feedback(self, tmp_path):
        from src.paper_trading.state import PortfolioState
        engine = _make_engine(tmp_path)
        state = PortfolioState.initial(200_000)
        trade = _sell_trade(pnl_pct=-0.06, reason="止损过紧被洗")
        report = engine._trigger_event_review(state, ["今日平仓 1 笔"], [trade])
        assert report and __import__("pathlib").Path(report).exists()
        # 亏损平仓已写入反馈（含错误类型）
        assert engine.feedback_collector.count() >= 1
        fb = engine.feedback_collector.get_by_signal("TRADE_600519")
        assert fb and fb[0].mistake_type.value == "stop_too_tight"
        assert engine.decision_journal.count() >= 1
