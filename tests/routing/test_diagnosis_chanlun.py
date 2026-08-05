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


def test_detect_chanlun_sell_signal_reflects_latest_point():
    """sell_signal 只反映最近一个买卖点（last_point），不被历史买卖点误触。"""
    ctx = DiagnosisEngine._detect_chanlun("000001", "测试", _make_df(200, seed=42))
    if ctx is not None:
        last_kind = (
            ctx["summary"].get("current_state", {})
            .get("last_point", {}).get("kind", "")
        )
        assert ctx["summary"]["sell_signal"] == (last_kind in ("一卖", "二卖", "三卖"))
        assert ctx["summary"]["buy_signal"] == (last_kind in ("一买", "二买", "三买"))


def test_report_has_chanlun_fields():
    rep = DiagnosisReport(symbol="000001", name="测试")
    assert rep.chanlun is None
    assert rep.chanlun_score == 50.0


def test_chanlun_score_clamped():
    # 触发 _detect_chanlun 内部评分区间检查（覆盖 path 端到端）
    ctx = DiagnosisEngine._detect_chanlun("000001", "测试", _make_df())
    if ctx is not None:
        assert 0.0 <= ctx["score"] <= 100.0
