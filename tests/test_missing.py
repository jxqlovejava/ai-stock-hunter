# -*- coding: utf-8 -*-
"""补齐缺失模块的测试: 盯盘、政策、Skill。"""

from __future__ import annotations


class TestAlerts:
    def test_price_alert(self):
        from src.output.alert import AlertManager
        mgr = AlertManager()
        mgr.add_price_alert("600519", "茅台", above=1300.0)
        triggered = mgr.check({"600519": 1310.0})
        assert len(triggered) == 1
        assert triggered[0].alert_type == "PRICE"

    def test_stop_loss_alert(self):
        from src.output.alert import AlertManager
        mgr = AlertManager()
        mgr.add_stop_loss_alert("000001", "平安银行", 10.0)
        triggered = mgr.check({"000001": 9.5})
        assert len(triggered) == 1
        assert triggered[0].severity == "CRITICAL"

    def test_no_trigger(self):
        from src.output.alert import AlertManager
        mgr = AlertManager()
        mgr.add_price_alert("600519", "茅台", above=2000.0)
        triggered = mgr.check({"600519": 1200.0})
        assert len(triggered) == 0

    def test_watchlist_scan(self):
        from src.output.alert import AlertManager
        mgr = AlertManager()
        ctx = {"000001": {"name": "平安银行", "stop_price": 9.5, "change_pct": -6.0}}
        alerts = mgr.scan_watchlist(["000001"], {"000001": 9.3}, ctx)
        assert len(alerts) == 2  # stop loss + 单日大跌

    def test_expired_cleanup(self):
        from src.output.alert import AlertManager
        mgr = AlertManager()
        mgr.add_price_alert("600519", "茅台", above=1300.0, expire_days=-1)  # already expired
        assert len(mgr.check({"600519": 1310.0})) == 0


class TestPolicy:
    def test_scan_finds_keywords(self):
        from src.policy.tracker import PolicyTracker
        tracker = PolicyTracker()
        text = "央行宣布降准0.5个百分点，释放长期流动性"
        signals = tracker.scan(text, "央行")
        assert len(signals) >= 1
        assert "降准" in signals[0].keywords
        assert "银行" in signals[0].affected_sectors

    def test_impact_assessment(self):
        from src.policy.tracker import PolicyTracker
        tracker = PolicyTracker()
        signals = tracker.scan("国务院发布注册制改革方案", "国务院")
        assert signals[0].impact_level == "HIGH"

    def test_no_keywords(self):
        from src.policy.tracker import PolicyTracker
        tracker = PolicyTracker()
        signals = tracker.scan("今日天气晴好", "test")
        assert len(signals) == 0


class TestSkillExists:
    def test_skill_file_exists(self):
        import os
        path = os.path.expanduser(
            "~/Documents/workspace/ai-stock-hunter/.claude/skills/stock-hunter/SKILL.md"
        )
        assert os.path.exists(path), "Claude Code Skill file missing"
