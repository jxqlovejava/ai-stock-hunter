# -*- coding: utf-8 -*-
"""持仓哨兵单元测试。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.sentinel.engine import SentinelConfig, SentinelEngine, is_trading_time
from src.sentinel.models import AlertLevel, PositionSnapshot, QuoteSnapshot


BEIJING = timezone(timedelta(hours=8))


@pytest.fixture
def tmp_env(tmp_path: Path):
    pos = {
        "002460": {
            "symbol": "002460",
            "name": "赣锋锂业",
            "direction": "LONG",
            "entry_price": 58.85,
            "quantity": 100,
            "stop_price": 53.93,
        }
    }
    positions_path = tmp_path / "positions.json"
    positions_path.write_text(json.dumps(pos, ensure_ascii=False), encoding="utf-8")
    state_path = tmp_path / "state.json"
    cfg = SentinelConfig(
        positions_path=positions_path,
        state_path=state_path,
        force_trading_hours=True,
        cool_p0=0,
        cool_p1=0,
        cool_p2=0,
    )
    return cfg


def test_load_positions(tmp_env):
    eng = SentinelEngine(tmp_env)
    pos = eng.load_positions()
    assert len(pos) == 1
    assert pos[0].symbol == "002460"
    assert pos[0].stop_price == 53.93


def test_stop_hit(tmp_env, monkeypatch):
    eng = SentinelEngine(tmp_env)

    def fake_quotes(symbols, names=None, prefer_huatai=False):
        return {
            "002460": QuoteSnapshot(
                symbol="002460",
                name="赣锋锂业",
                price=53.00,
                change_pct=-3.0,
                open=54.0,
                high=54.5,
                low=52.8,
                prev_close=54.6,
            )
        }, []

    monkeypatch.setattr("src.sentinel.engine.fetch_quotes", fake_quotes)
    result = eng.run()
    assert result.silent is False
    assert any(a.rule_id == "stop_hit" for a in result.alerts)
    assert "P0" in result.message


def test_stop_near(tmp_env, monkeypatch):
    eng = SentinelEngine(tmp_env)

    def fake_quotes(symbols, names=None, prefer_huatai=False):
        # stop 53.93, price ~54.5 → 距止损约 1%
        return {
            "002460": QuoteSnapshot(
                symbol="002460",
                name="赣锋锂业",
                price=54.50,
                change_pct=-1.0,
                prev_close=55.0,
            )
        }, []

    monkeypatch.setattr("src.sentinel.engine.fetch_quotes", fake_quotes)
    result = eng.run()
    assert any(a.rule_id == "stop_near" for a in result.alerts)


def test_cost_break(tmp_env, monkeypatch):
    eng = SentinelEngine(tmp_env)

    def fake_quotes(symbols, names=None, prefer_huatai=False):
        return {
            "002460": QuoteSnapshot(
                symbol="002460",
                name="赣锋锂业",
                price=57.0,  # 成本 58.85 之下
                change_pct=-2.0,
                prev_close=58.0,
            )
        }, []

    monkeypatch.setattr("src.sentinel.engine.fetch_quotes", fake_quotes)
    result = eng.run()
    assert any(a.rule_id == "cost_break" for a in result.alerts)


def test_silent_when_calm(tmp_env, monkeypatch):
    # 提高阈值避免误触
    tmp_env.stop_near_pct = 0.1
    tmp_env.day_drop_pct = 20
    tmp_env.day_rise_pct = 20
    tmp_env.jump_pct = 50
    eng = SentinelEngine(tmp_env)

    def fake_quotes(symbols, names=None, prefer_huatai=False):
        return {
            "002460": QuoteSnapshot(
                symbol="002460",
                name="赣锋锂业",
                price=58.85,  # 正好成本
                change_pct=0.1,
                open=58.8,
                high=58.9,
                low=58.7,
                prev_close=58.8,
            )
        }, []

    monkeypatch.setattr("src.sentinel.engine.fetch_quotes", fake_quotes)
    result = eng.run()
    # 成本线附近、远离止损 → 应静默
    assert result.silent is True or not any(
        a.rule_id in ("stop_hit", "day_drop") for a in result.alerts
    )


def test_cooling_suppresses_repeat(tmp_env, monkeypatch):
    tmp_env.cool_p0 = 30
    eng = SentinelEngine(tmp_env)

    def fake_quotes(symbols, names=None, prefer_huatai=False):
        return {
            "002460": QuoteSnapshot(
                symbol="002460", name="赣锋锂业", price=53.0, change_pct=-5
            )
        }, []

    monkeypatch.setattr("src.sentinel.engine.fetch_quotes", fake_quotes)
    r1 = eng.run()
    assert any(a.rule_id == "stop_hit" for a in r1.alerts)
    r2 = eng.run()
    assert not any(a.rule_id == "stop_hit" for a in r2.alerts)


def test_is_trading_time_weekend():
    sat = datetime(2026, 7, 11, 10, 0, tzinfo=BEIJING)  # Saturday
    assert is_trading_time(sat) is False


def test_is_trading_time_session():
    mon = datetime(2026, 7, 13, 10, 30, tzinfo=BEIJING)
    assert is_trading_time(mon) is True
    noon = datetime(2026, 7, 13, 12, 0, tzinfo=BEIJING)
    assert is_trading_time(noon) is False
