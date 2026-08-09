# -*- coding: utf-8 -*-
"""trade-track 盈亏归因字段（P2-2）序列化与向后兼容测试。"""

import os
import tempfile

from src.kelly.tracker import TradeRecord, TradeTracker


def _record(attribution="unknown"):
    return TradeRecord(
        symbol="600519",
        entry_date="2026-01-15",
        exit_date="2026-02-01",
        entry_price=1500.0,
        exit_price=1600.0,
        shares=100,
        direction="LONG",
        notes="测试",
        attribution=attribution,
    )


def test_trade_record_attribution_roundtrip():
    rec = _record("lucky_market")
    d = rec.to_dict()
    assert d["attribution"] == "lucky_market"
    back = TradeRecord.from_dict(d)
    assert back.attribution == "lucky_market"


def test_trade_record_backward_compat_no_attribution():
    """旧数据无 attribution 字段 → 默认 unknown。"""
    d = _record().to_dict()
    del d["attribution"]
    rec = TradeRecord.from_dict(d)
    assert rec.attribution == "unknown"


def test_tracker_persists_attribution():
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "trades.json"
        t1 = TradeTracker(path=path)
        t1.track(_record("system_executed"))
        t2 = TradeTracker(path=path)
        trades = t2.get_trades("600519")
        assert trades[0].attribution == "system_executed"
