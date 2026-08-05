# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

from src.indicators.chanlun.analyzer import ChanlunAnalyzer


def _make_df(n=120, seed=42):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0, 1, n)
    low = close - rng.uniform(0, 1, n)
    open_ = close + rng.normal(0, 0.3, n)
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": 1e6}, index=idx)


def test_analyzer_produces_result():
    df = _make_df()
    r = ChanlunAnalyzer().analyze(df, "000001", "测试")
    assert r.symbol == "000001"
    assert r.freq == "D"
    assert len(r.source_citations) >= 1
    assert 0.0 <= r.confidence <= 1.0
    assert r.current_state["last_close"] == float(df["close"].iloc[-1])


def test_analyzer_data_gap_short():
    df = _make_df(20)                       # <30 根
    r = ChanlunAnalyzer().analyze(df, "000001", "测试")
    assert r.bis == [] and r.zhongshus == []
    assert "gap" in r.current_state


def test_analyzer_rangeindex_date_col_normalized():
    """回归: 腾讯/mootdx 等源返回 RangeIndex + 「日期」列，dt 必须是真实日期。"""
    rng = np.random.default_rng(7)
    n = 120
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    dates = pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d")
    df = pd.DataFrame({
        "日期": dates, "open": close + rng.normal(0, 0.3, n),
        "high": close + rng.uniform(0, 1, n), "low": close - rng.uniform(0, 1, n),
        "close": close, "volume": 1e6,
    })                                       # index 默认 RangeIndex
    assert not isinstance(df.index, pd.DatetimeIndex)
    r = ChanlunAnalyzer().analyze(df, "000001", "测试")
    assert r.bis and r.zhongshus
    # 笔 dt 必须可格式化（strftime），不能是整数位置
    for b in r.bis:
        assert hasattr(b.start_dt, "strftime") and hasattr(b.end_dt, "strftime")
    for p in r.points:
        assert hasattr(p.dt, "strftime")
    # 现价位置取整须基于归一化后 df 的收盘
    assert r.current_state["last_close"] == float(close[-1])


def test_analyzer_backend_self_without_czsc(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "czsc", None)  # 模拟 czsc 不可用
    df = _make_df()
    r = ChanlunAnalyzer(use_czsc=True).analyze(df, "000001", "测试")
    assert r.backend == "self"


def test_to_signal_long_only():
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
    points = detect_points(bis, zss, {4: {"type": "bottom", "bi_index": 4}})
    signals = ChanlunAnalyzer.to_signal(points)
    assert any("一买" in s["kind"] for s in signals["entry"])
    assert any("二买" in s["kind"] for s in signals["entry"])
    assert all(s["kind"] not in ("一卖", "二卖", "三卖") for s in signals["entry"])
