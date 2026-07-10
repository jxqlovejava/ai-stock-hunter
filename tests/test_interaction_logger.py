"""Tests for interaction logger module."""

import io
import json
import tempfile
from pathlib import Path

import pytest

from src.interaction import InteractionLogger


@pytest.fixture
def tmp_logger():
    with tempfile.TemporaryDirectory() as d:
        log_path = Path(d) / "test_log.jsonl"
        yield InteractionLogger(log_path=str(log_path))


class TestInteractionLogger:
    def test_log_and_tail(self, tmp_logger):
        tmp_logger.log(command="diagnose", args=["002460"], output="评分 52 HOLD", duration_ms=150)
        tmp_logger.log(command="sweep", args=[], output="3 支预警", duration_ms=80)

        entries = tmp_logger.tail(10)
        assert len(entries) == 2
        assert entries[0]["command"] == "diagnose"
        assert entries[1]["command"] == "sweep"
        assert entries[0]["exit_code"] == 0

    def test_log_error(self, tmp_logger):
        tmp_logger.log(command="diagnose", args=["invalid"], output="错误", exit_code=1)
        entries = tmp_logger.tail(1)
        assert entries[0]["exit_code"] == 1

    def test_search(self, tmp_logger):
        tmp_logger.log(command="diagnose", args=["002460"], output="赣锋锂业 评分 52")
        tmp_logger.log(command="sweep", args=[], output="扫雷完成")

        results = tmp_logger.search("赣锋")
        assert len(results) >= 1
        assert results[0]["command"] == "diagnose"

        results2 = tmp_logger.search("不存在的关键词")
        assert len(results2) == 0

    def test_stats(self, tmp_logger):
        tmp_logger.log(command="diagnose", args=["002460"], duration_ms=100)
        tmp_logger.log(command="diagnose", args=["600519"], duration_ms=200)
        tmp_logger.log(command="sweep", args=[], duration_ms=50, exit_code=1)

        s = tmp_logger.stats()
        assert s["total"] == 3
        assert s["errors"] == 1
        assert s["total_duration_ms"] == 350
        assert s["avg_duration_ms"] == 116

    def test_recent_commands(self, tmp_logger):
        tmp_logger.log(command="diagnose")
        tmp_logger.log(command="sweep")
        tmp_logger.log(command="diagnose")

        cmds = tmp_logger.recent_commands()
        assert "diagnose" in cmds
        assert "sweep" in cmds

    def test_empty_log(self, tmp_logger):
        assert tmp_logger.tail(10) == []
        assert tmp_logger.search("test") == []
        assert tmp_logger.stats() == {"total": 0, "commands": {}}

    def test_truncation_long_output(self, tmp_logger):
        long_output = "A" * 2000
        tmp_logger.log(command="test", output=long_output)
        entry = tmp_logger.tail(1)[0]
        summary = entry["summary"]
        assert len(summary) < 2000
        assert "truncated" in summary

    def test_ansi_stripping(self, tmp_logger):
        colored = "\x1b[31m错误\x1b[0m 正常"
        tmp_logger.log(command="test", output=colored)
        entry = tmp_logger.tail(1)[0]
        assert "\x1b" not in entry["summary"]
        assert "错误" in entry["summary"]
