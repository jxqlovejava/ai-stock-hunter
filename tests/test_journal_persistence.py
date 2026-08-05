# -*- coding: utf-8 -*-
"""DecisionJournal SQLite 持久化测试。

覆盖:
  ① log 后 SQLite 有记录（含全部字段 + JSON lessons）
  ② 重建 DecisionJournal（同路径）从 SQLite 恢复 entries
  ③ 路径可注入（tmp_path 隔离）+ $BAIZE_JOURNAL_PATH 覆盖
  ④ 无 SQLite / 写入失败降级内存态（不崩溃）
  ⑤ AlphaReport 序列化往返
"""

from __future__ import annotations

import sqlite3

import pytest


def _rows(path, sql="SELECT * FROM decisions ORDER BY id ASC"):
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


class TestPersistence:
    def test_log_writes_row_to_sqlite(self, tmp_path):
        """① log 后 SQLite 表中有记录，字段完整。"""
        from src.learner import DecisionJournal
        path = tmp_path / "journal.db"
        j = DecisionJournal(db_path=str(path))
        j.log("600519", "BUY", "BUY", "觉得便宜", "NORMAL",
              outcome_1w=0.05, outcome_1m=0.08, lessons=["低估值逻辑被验证"], mistake_type="chased_move")
        rows = _rows(path)
        assert len(rows) == 1
        row = rows[0]
        assert row[2] == "600519"      # symbol
        assert row[3] == "BUY"         # system_action
        assert row[4] == "BUY"         # user_action
        assert row[5] == "觉得便宜"     # user_reason
        assert row[6] == "NORMAL"      # market_sentiment
        assert row[7] == pytest.approx(0.05)   # outcome_1w
        assert row[8] == pytest.approx(0.08)   # outcome_1m
        assert "低估值逻辑被验证" in row[9]    # lessons (JSON)
        assert row[10] == "chased_move"        # mistake_type

    def test_reload_restores_entries(self, tmp_path):
        """② 同路径重建能从 SQLite 恢复全部 entries，且 weekly_review 可用。"""
        from src.learner import DecisionJournal
        path = tmp_path / "journal.db"
        j1 = DecisionJournal(db_path=str(path))
        j1.log("600519", "BUY", "BUY", "同意系统", "NORMAL")
        j1.log("000001", "SELL", "HOLD", "再看看", "PANIC")
        j2 = DecisionJournal(db_path=str(path))
        assert j2.count() == 2
        syms = {e["symbol"] for e in j2.entries}
        assert syms == {"600519", "000001"}
        assert "600519" in j2.weekly_review()

    def test_empty_db_returns_empty(self, tmp_path):
        """无历史时重建不崩溃，返回空日志。"""
        from src.learner import DecisionJournal
        j = DecisionJournal(db_path=str(tmp_path / "fresh.db"))
        assert j.count() == 0
        assert "无交易" in j.weekly_review()

    def test_path_injection_isolates(self, tmp_path):
        """③ 不同 db_path 之间数据隔离（tmp_path 注入）。"""
        from src.learner import DecisionJournal
        p1 = tmp_path / "a.db"
        p2 = tmp_path / "b.db"
        DecisionJournal(db_path=str(p1)).log("600519", "BUY", "BUY")
        j2 = DecisionJournal(db_path=str(p2))
        assert j2.count() == 0
        j3 = DecisionJournal(db_path=str(p1))
        assert j3.count() == 1

    def test_env_override(self, tmp_path, monkeypatch):
        """③ $BAIZE_JOURNAL_PATH 覆盖默认路径。"""
        from src.learner import DecisionJournal
        monkeypatch.setenv("BAIZE_JOURNAL_PATH", str(tmp_path / "env.db"))
        j = DecisionJournal()
        j.log("600519", "BUY", "BUY")
        assert (tmp_path / "env.db").exists()

    def test_default_path_usable(self, tmp_path, monkeypatch):
        """默认路径 data/journal.db 也可用（指向 tmp_path 避免污染仓库）。"""
        from src.learner import DecisionJournal
        monkeypatch.setenv("BAIZE_JOURNAL_PATH", str(tmp_path / "default.db"))
        j = DecisionJournal()
        j.log("600519", "BUY", "BUY")
        j2 = DecisionJournal()
        assert j2.count() == 1


class TestDegradation:
    def test_init_failure_degrades_to_memory(self, tmp_path):
        """④ 无 SQLite 可用（父路径为普通文件）时降级内存态，不崩溃。"""
        from src.learner import DecisionJournal
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir")
        j = DecisionJournal(db_path=str(blocker / "journal.db"))
        j.log("600519", "BUY", "BUY")
        assert j.count() == 1
        assert j.entries[0]["symbol"] == "600519"
        assert not j._persist

    def test_write_failure_degrades_to_memory(self, tmp_path, monkeypatch):
        """④ 写入失败时保持内存态，不崩溃。"""
        from src.learner import DecisionJournal

        def boom(self, entry):
            raise sqlite3.OperationalError("disk I/O error")

        path = tmp_path / "journal.db"
        j = DecisionJournal(db_path=str(path))
        monkeypatch.setattr(DecisionJournal, "_save_entry", boom)
        j.log("600519", "BUY", "BUY")
        assert j.count() == 1           # 仍保留在内存
        assert not j._persist           # 已降级

    def test_memory_mode(self):
        """db_path=':memory:' 不落盘，行为等同内存态。"""
        from src.learner import DecisionJournal
        j = DecisionJournal(db_path=":memory:")
        j.log("600519", "BUY", "BUY")
        assert j.count() == 1
        assert j.entries[0]["symbol"] == "600519"


class TestAlphaRoundtrip:
    def test_alpha_report_serialization_roundtrip(self):
        """⑤ AttributionReport 序列化 → 反序列化后字段完整。"""
        from datetime import datetime
        from src.alpha.attribution import AttributionReport
        from src.learner import DecisionJournal
        ar = AttributionReport(
            symbol="600519",
            period_start=datetime(2026, 8, 1),
            period_end=datetime(2026, 8, 5),
            total_return_pct=12.3,
            market_beta_return_pct=2.0,
            alpha_return_pct=10.0,
            alpha_quality_score=80.0,
            key_insights=["左侧逻辑被验证"],
        )
        j = DecisionJournal(db_path=":memory:")
        restored = j._deserialize_alpha(j._serialize_alpha(ar))
        assert restored is not None
        assert restored.symbol == "600519"
        assert restored.alpha_return_pct == pytest.approx(10.0)
        assert restored.market_beta_return_pct == pytest.approx(2.0)
        assert restored.period_start == datetime(2026, 8, 1)
        assert restored.is_alpha_driven is True

    def test_alpha_report_roundtrips_through_sqlite(self, tmp_path):
        """⑤ 带 Alpha 归因的 log 落盘后，重建能恢复 alpha_report。"""
        from src.alpha.schema import AlphaProfile
        from src.learner import DecisionJournal
        path = tmp_path / "journal.db"
        j1 = DecisionJournal(db_path=str(path))
        j1.log("600519", "BUY", "BUY", "左侧布局", "NORMAL",
               entry_alpha=AlphaProfile(), total_return_pct=12.3,
               market_return_pct=2.0, sector_return_pct=1.0, holding_days=5)
        j2 = DecisionJournal(db_path=str(path))
        ar = j2.entries[0]["alpha_report"]
        assert ar is not None
        assert ar.symbol == "600519"
        assert ar.alpha_return_pct == pytest.approx(10.0, abs=1.0)
        # weekly_review 展示 Alpha/Beta 驱动行
        review = j2.weekly_review()
        assert ("Alpha 驱动" in review) or ("Beta 驱动" in review)

    def test_none_alpha_report_handled(self):
        from src.learner import DecisionJournal
        j = DecisionJournal(db_path=":memory:")
        assert j._serialize_alpha(None) is None
        assert j._deserialize_alpha(None) is None
