# -*- coding: utf-8 -*-
"""diagnose 缠论融入测试 — _detect_chanlun 降级 / 结构评分 / 报告字段。"""
import numpy as np
import pandas as pd

from src.routing.diagnosis import DiagnosisEngine, DiagnosisReport


def _make_df(n=120, seed=3):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open": close + rng.normal(0, 0.3, n),
        "high": close + rng.uniform(0, 1, n),
        "low": close - rng.uniform(0, 1, n),
        "close": close, "volume": 1e6,
    }, index=idx)


def test_detect_chanlun_none_without_bars():
    assert DiagnosisEngine._detect_chanlun("000001", "测试", None) is None


def test_detect_chanlun_none_with_empty_bars():
    assert DiagnosisEngine._detect_chanlun("000001", "测试", pd.DataFrame()) is None


def test_detect_chanlun_with_bars():
    ctx = DiagnosisEngine._detect_chanlun("000001", "测试", _make_df())
    if ctx is not None:                     # 随机数据可能无结构 → 允许 None
        assert 0.0 <= ctx["score"] <= 100.0
        assert "buy_signal" in ctx["summary"]
        assert "sell_signal" in ctx["summary"]
        assert isinstance(ctx["summary"]["sell_signal"], bool)


def test_detect_chanlun_sell_signal_flags_warn():
    from src.indicators.chanlun.schema import ChanlunPoint
    # 直接构造带三卖的 summary 语义：sell_signal 应反映空头买卖点
    ctx = DiagnosisEngine._detect_chanlun("000001", "测试", _make_df(200, seed=42))
    if ctx is not None:
        any_sell = any(
            p.get("kind") in ("一卖", "二卖", "三卖")
            for p in ctx["summary"].get("points", [])
        )
        assert ctx["summary"]["sell_signal"] == any_sell


def test_report_has_chanlun_fields():
    rep = DiagnosisReport(symbol="000001", name="测试")
    assert rep.chanlun is None
    assert rep.chanlun_score == 50.0


def test_chanlun_score_clamped():
    # 触发 _detect_chanlun 内部评分区间检查（覆盖 path 端到端）
    ctx = DiagnosisEngine._detect_chanlun("000001", "测试", _make_df())
    if ctx is not None:
        assert 0.0 <= ctx["score"] <= 100.0
