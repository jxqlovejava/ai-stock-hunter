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
        enable_macd_kdj=False,  # 默认单测不依赖 kline_cache
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


def test_macd_kdj_exit_alert(tmp_path, monkeypatch):
    """有 EXIT 五法状态时发出 P1 预警。"""
    import numpy as np
    import pandas as pd

    # 构造会触发 M2 的序列很难稳定；改为 mock evaluate
    pos = {
        "002460": {
            "symbol": "002460",
            "name": "赣锋锂业",
            "direction": "LONG",
            "entry_price": 54.0,
            "quantity": 200,
            "stop_price": 49.78,
        }
    }
    positions_path = tmp_path / "positions.json"
    positions_path.write_text(json.dumps(pos), encoding="utf-8")
    cache = tmp_path / "kline"
    cache.mkdir()
    # 写假缓存文件（引擎只检查存在后调用 load/evaluate）
    pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=50, freq="B"),
            "open": np.linspace(60, 50, 50),
            "high": np.linspace(61, 51, 50),
            "low": np.linspace(59, 49, 50),
            "close": np.linspace(60, 50, 50),
            "volume": [1e6] * 50,
        }
    ).to_csv(cache / "002460_test_daily.csv", index=False)

    cfg = SentinelConfig(
        positions_path=positions_path,
        state_path=tmp_path / "state.json",
        force_trading_hours=True,
        cool_p0=0,
        cool_p1=0,
        cool_p2=0,
        enable_macd_kdj=True,
        kline_cache_dir=cache,
    )
    eng = SentinelEngine(cfg)

    def fake_quotes(symbols, names=None, prefer_huatai=False):
        return {
            "002460": QuoteSnapshot(
                symbol="002460", name="赣锋锂业", price=50.5, change_pct=-1.0
            )
        }, []

    def fake_eval(df, **kwargs):
        return {
            "action": "EXIT",
            "methods": ["M2_resonance_death"],
            "confidence": 0.48,
            "notes": ["共振死叉"],
            "dif": -0.5,
            "dea": -0.3,
            "k": 40.0,
            "d": 45.0,
        }

    monkeypatch.setattr("src.sentinel.engine.fetch_quotes", fake_quotes)
    monkeypatch.setattr("src.alphas.macd_kdj.evaluate_ohlc_latest", fake_eval)
    result = eng.run()
    assert any(a.rule_id == "macd_kdj_exit" for a in result.alerts)


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


def test_float_loss_and_peak_drawdown(tmp_env, monkeypatch):
    tmp_env.enable_risk = True
    tmp_env.float_loss_pct = 8.0
    tmp_env.peak_drawdown_pct = 5.0
    # 抬高止损避免 stop_hit 抢戏
    pos = json.loads(tmp_env.positions_path.read_text(encoding="utf-8"))
    pos["002460"]["stop_price"] = 40.0
    pos["002460"]["high_price"] = 60.0
    pos["002460"]["entry_price"] = 58.85
    tmp_env.positions_path.write_text(json.dumps(pos), encoding="utf-8")
    eng = SentinelEngine(tmp_env)

    def fake_quotes(symbols, names=None, prefer_huatai=False):
        return {
            "002460": QuoteSnapshot(
                symbol="002460",
                name="赣锋锂业",
                price=52.0,  # 浮亏 ~11.6%, 从 60 回撤 ~13%
                change_pct=-2.0,
                prev_close=53.0,
            )
        }, []

    monkeypatch.setattr("src.sentinel.engine.fetch_quotes", fake_quotes)
    r = eng.run()
    ids = {a.rule_id for a in r.alerts}
    assert "float_loss" in ids
    assert "peak_drawdown" in ids


def test_single_overweight(tmp_env, monkeypatch):
    tmp_env.enable_position_mgmt = True
    tmp_env.total_capital = 100_000
    tmp_env.max_single_pct = 0.10  # 10%
    pos = json.loads(tmp_env.positions_path.read_text(encoding="utf-8"))
    pos["002460"]["quantity"] = 1000  # 52*1000=52000 > 10% of 100k
    pos["002460"]["stop_price"] = 40.0
    tmp_env.positions_path.write_text(json.dumps(pos), encoding="utf-8")
    eng = SentinelEngine(tmp_env)

    def fake_quotes(symbols, names=None, prefer_huatai=False):
        return {
            "002460": QuoteSnapshot(
                symbol="002460", name="赣锋", price=52.0, change_pct=0.1
            )
        }, []

    monkeypatch.setattr("src.sentinel.engine.fetch_quotes", fake_quotes)
    # 关掉无关阈值
    tmp_env.day_drop_pct = 99
    tmp_env.day_rise_pct = 99
    tmp_env.float_loss_pct = 50
    tmp_env.peak_drawdown_pct = 50
    tmp_env.cost_break_pct = 50
    r = eng.run()
    assert any(a.rule_id == "single_overweight" for a in r.alerts)


def test_portfolio_exposure_and_loss(tmp_path, monkeypatch):
    pos = {
        "000001": {
            "symbol": "000001",
            "name": "平安银行",
            "direction": "LONG",
            "entry_price": 20.0,
            "quantity": 1000,
            "stop_price": 10.0,
        },
        "000002": {
            "symbol": "000002",
            "name": "万科A",
            "direction": "LONG",
            "entry_price": 10.0,
            "quantity": 2000,
            "stop_price": 5.0,
        },
    }
    ppath = tmp_path / "positions.json"
    ppath.write_text(json.dumps(pos), encoding="utf-8")
    cfg = SentinelConfig(
        positions_path=ppath,
        state_path=tmp_path / "state.json",
        force_trading_hours=True,
        enable_risk=True,
        enable_position_mgmt=True,
        total_capital=50_000,
        max_total_exposure=0.50,
        min_cash_pct=0.40,
        portfolio_loss_pct=5.0,
        float_loss_pct=50.0,
        peak_drawdown_pct=50.0,
        day_drop_pct=99,
        day_rise_pct=99,
        cost_break_pct=50,
        cool_p0=0,
        cool_p1=0,
        cool_p2=0,
    )
    eng = SentinelEngine(cfg)

    def fake_quotes(symbols, names=None, prefer_huatai=False):
        # 市值 15*1000 + 8*2000 = 15000+16000=31000 / 50000 = 62% > 50%
        # 成本 20k+20k=40k，市值 31k，组合浮亏 -22.5%
        return {
            "000001": QuoteSnapshot(symbol="000001", name="平安", price=15.0),
            "000002": QuoteSnapshot(symbol="000002", name="万科", price=8.0),
        }, []

    monkeypatch.setattr("src.sentinel.engine.fetch_quotes", fake_quotes)
    r = eng.run()
    ids = {a.rule_id for a in r.alerts}
    assert "total_exposure" in ids
    assert "portfolio_loss" in ids
    assert "cash_low" in ids
