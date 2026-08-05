# -*- coding: utf-8 -*-
"""tactics 缠论融入测试 — chanlun_score 映射 / TacticalSnapshot 字段 / summary 契约。"""
import numpy as np
import pandas as pd

from src.indicators.chanlun.analyzer import ChanlunAnalyzer
from src.routing.tactics import TacticalSnapshot, _chanlun_score, _apply_chanlun_snapshot


def _make_df(n=120, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open": close + rng.normal(0, 0.3, n),
        "high": close + rng.uniform(0, 1, n),
        "low": close - rng.uniform(0, 1, n),
        "close": close, "volume": 1e6,
    }, index=idx)


def _make_point(kind, price=100.0, confidence=0.8, rationale="x"):
    from src.indicators.chanlun.schema import ChanlunPoint
    return ChanlunPoint(kind=kind, dt=pd.Timestamp("2025-06-01"),
                        price=price, confidence=confidence, rationale=rationale)


# ── 契约: summary dict 与 tactics 消费字段一致 ─────────────────────
def test_chanlun_on_bars_df_matches_tactics_shape():
    df = _make_df()
    r = ChanlunAnalyzer().analyze(df, "000001", "测试")
    summary = r.to_summary_dict()
    assert {"backend", "bi_count", "zhongshu_count", "last_zs",
            "points", "current_state", "signals", "confidence"} <= set(summary)
    assert summary["signals"].keys() == {"entry", "exit"}
    for sig in summary["signals"]["entry"]:
        assert sig["kind"] in ("一买", "二买", "三买")


# ── _chanlun_score 评分映射 ─────────────────────────────────────────
def test_chanlun_score_neutral_without_points():
    assert _chanlun_score([]) == 50.0


def test_chanlun_score_buy_lifts_above_neutral():
    score = _chanlun_score([_make_point("一买", confidence=0.8)])
    assert score > 55.0


def test_chanlun_score_sell_drags_below_neutral():
    score = _chanlun_score([_make_point("三卖", confidence=0.8)])
    assert score < 45.0


def test_chanlun_score_zhongshu_position_adjusts():
    base_sell = _chanlun_score([_make_point("三卖", confidence=0.8)], position="中枢上方")
    below_sell = _chanlun_score([_make_point("三卖", confidence=0.8)], position="中枢下方")
    assert below_sell < base_sell
    assert base_sell - below_sell >= 14.0      # 8(中枢下) + 6(中枢上) 价差


def test_chanlun_score_clamped_0_100():
    assert _chanlun_score([_make_point("一买", confidence=1.0)], position="中枢上方") <= 100.0
    assert _chanlun_score([_make_point("三卖", confidence=1.0)], position="中枢下方") >= 0.0


# ── TacticalSnapshot 字段存在性与默认值 ─────────────────────────────
def test_snapshot_has_chanlun_fields():
    snap = TacticalSnapshot(symbol="000001", name="测试")
    assert snap.chanlun_score == 50.0
    assert snap.chanlun_result is None


# ── _apply_chanlun_snapshot: _dim_technical 缠论块的实质逻辑 ────────
def test_apply_chanlun_snapshot_populates_snapshot_and_ctx():
    snap = TacticalSnapshot(symbol="000001", name="测试")
    res = ChanlunAnalyzer().analyze(_make_df(), "000001", "测试")
    ctx = _apply_chanlun_snapshot(snap, res)
    assert snap.chanlun_result["confidence"] == res.confidence
    assert 0.0 <= snap.chanlun_score <= 100.0
    # 所有买卖点都以 CHANLUN_ 前缀并入入场/出场信号
    entry_kinds = {s["type"].removeprefix("CHANLUN_") for s in snap.entry_signals}
    exit_kinds = {s["type"].removeprefix("CHANLUN_") for s in snap.exit_signals}
    all_kinds = entry_kinds | exit_kinds
    assert all_kinds == {p.kind for p in res.points} if res.points else True
    for sig in snap.entry_signals:
        assert sig["type"].startswith("CHANLUN_")
        assert sig["zone_low"] <= sig["zone_high"]
    # doctrine_ctx 注入字段齐全
    assert {"chanlun_sell_signal", "chanlun_zs_break",
            "chanlun_buy_confirmed", "chanlun_bihuang_down"} <= set(ctx)
    assert isinstance(ctx["chanlun_zs_break"], bool)


def test_apply_chanlun_snapshot_sell_ctx_on_last_sell():
    snap = TacticalSnapshot(symbol="000001", name="测试")
    res = ChanlunAnalyzer().analyze(_make_df(200, seed=3), "000001", "测试")
    ctx = _apply_chanlun_snapshot(snap, res)
    if res.points and res.current_state.get("last_point", {}).get("kind") in ("一卖", "二卖", "三卖"):
        assert ctx["chanlun_sell_signal"] == "sell"
    else:
        assert ctx["chanlun_sell_signal"] in ("", "sell")


def test_chanlun_points_mapping_produces_buy1():
    from src.indicators.chanlun.points import detect_points
    from src.indicators.chanlun.core.zhongshu import detect_zhongshus
    from src.indicators.chanlun.schema import Bi, Fractal

    def _bi(direction, high, low, area=0.0):
        if direction == "up":
            fa, fb = Fractal(mark="D", dt=0, high=low + 1, low=low, fx=low, index=0), \
                     Fractal(mark="G", dt=5, high=high, low=high - 1, fx=high, index=5)
        else:
            fa, fb = Fractal(mark="G", dt=0, high=high, low=high - 1, fx=high, index=0), \
                     Fractal(mark="D", dt=5, high=low + 1, low=low, fx=low, index=5)
        return Bi(direction=direction, start_fx=fa, end_fx=fb, high=high, low=low,
                  length=5, macd_area=area, start_dt=0, end_dt=5)

    bis = [_bi("down", 40, 30, 100.0), _bi("up", 36, 32, 30.0), _bi("down", 35, 31, 80.0),
           _bi("up", 34, 33, 20.0), _bi("down", 30, 24, 40.0), _bi("up", 30, 26, 20.0),
           _bi("down", 27, 25, 30.0)]
    zss = detect_zhongshus(bis)
    pts = detect_points(bis, zss, {4: {"type": "bottom", "bi_index": 4}})
    assert any(p.kind in ("一买", "二买", "三买") for p in pts)
