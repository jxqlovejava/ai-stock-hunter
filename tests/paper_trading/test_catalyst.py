# -*- coding: utf-8 -*-
"""催化信号监控器测试 (2026-08-08).

覆盖: 价格阈值触发/不触发 / 新闻关键词匹配 / 去重。
纯函数/快照级, 不触发真实网络。
"""
import json
from pathlib import Path

from src.paper_trading.catalyst import (
    _dedup_ok,
    _load_dedup,
    check_price,
    check_news,
)


class TestDedup:
    def setup_method(self):
        import src.paper_trading.catalyst as c
        self._orig = c.DEDUP_PATH
        c.DEDUP_PATH = Path("/tmp/catalyst_dedup_test.json")
        if c.DEDUP_PATH.exists():
            c.DEDUP_PATH.unlink()

    def teardown_method(self):
        import src.paper_trading.catalyst as c
        c.DEDUP_PATH = self._orig

    def test_first_ok_then_blocked(self):
        assert _dedup_ok("price:600089", 24) is True
        assert _dedup_ok("price:600089", 24) is False


class TestPriceCheck:
    def _quote(self, price):
        from types import SimpleNamespace
        return SimpleNamespace(price=price)

    def test_trigger_below_threshold(self, monkeypatch):
        from types import SimpleNamespace
        import src.paper_trading.catalyst as c
        rules = {"price_alerts": [
            {"symbol": "600089", "name": "特变电工", "threshold": 18.13,
             "direction": "<=", "message": "特变电工进入买点区"}
        ]}
        monkeypatch.setattr(
            "src.paper_trading.catalyst._dedup_ok", lambda *a, **k: True)
        monkeypatch.setattr(
            "src.data.aggregator.DataAggregator.get_quote",
            lambda self, sym, mkt: SimpleNamespace(price=18.0))
        hits = check_price(rules)
        assert len(hits) == 1 and "买点区" in hits[0]

    def test_no_trigger_above_threshold(self, monkeypatch):
        from types import SimpleNamespace
        import src.paper_trading.catalyst as c
        rules = {"price_alerts": [
            {"symbol": "600089", "name": "特变电工", "threshold": 18.13,
             "direction": "<=", "message": "买点区"}
        ]}
        monkeypatch.setattr(
            "src.paper_trading.catalyst._dedup_ok", lambda *a, **k: True)
        monkeypatch.setattr(
            "src.data.aggregator.DataAggregator.get_quote",
            lambda self, sym, mkt: SimpleNamespace(price=21.0))
        assert check_price(rules) == []


class TestNewsCheck:
    def test_keyword_all_match(self, monkeypatch):
        import src.paper_trading.catalyst as c
        rules = {"news_keywords": [
            {"keywords": ["特高压", "招标"], "message": "特高压招标落地"}
        ]}
        monkeypatch.setattr(
            "src.paper_trading.catalyst._dedup_ok", lambda *a, **k: True)
        monkeypatch.setattr(
            "src.data.eastmoney_fallback.fetch_em_global_news",
            lambda page_size=80: [
                {"title": "国网2026特高压招标结果公布", "summary": "多家中标",
                 "time": "2026-08-08 10:00"}
            ])
        hits = check_news(rules)
        assert len(hits) == 1 and "特高压招标落地" in hits[0]

    def test_partial_keyword_no_match(self, monkeypatch):
        import src.paper_trading.catalyst as c
        rules = {"news_keywords": [
            {"keywords": ["特高压", "招标"], "message": "催化"}
        ]}
        monkeypatch.setattr(
            "src.paper_trading.catalyst._dedup_ok", lambda *a, **k: True)
        monkeypatch.setattr(
            "src.data.eastmoney_fallback.fetch_em_global_news",
            lambda page_size=80: [
                {"title": "某公司发布年报", "summary": "业绩增长", "time": ""}
            ])
        assert check_news(rules) == []
