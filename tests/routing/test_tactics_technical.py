# -*- coding: utf-8 -*-
"""tactics 技术六维评分测试 — P0-1：因子帧注入后六维真实打分（非全 50 空转）。

根因复现: _dim_technical() 只把原始 OHLCV 帧传给 TechnicalAnalyzer，
_compute_factor_scores() 对每个因子 panel.get(fid) 返回空 → 六维全落默认 50。
修复: 通过 _inject_technical_factors() 注入 17 个技术因子帧。
"""
import numpy as np
import pandas as pd

from src.routing.technical import TechnicalAnalyzer
from src.routing.tactics import _TECH_FACTOR_IDS, _inject_technical_factors

SYMBOL = "000001"


def _make_df(n=300, seed=42):
    """带温和漂移的随机游走 K 线，保证多数因子值显著偏离 50。"""
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0.02, 0.8, n))
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "open": close + rng.normal(0, 0.3, n),
        "high": close + rng.uniform(0, 1, n),
        "low": close - rng.uniform(0, 1, n),
        "close": close,
        "volume": rng.uniform(8e5, 1.2e6, n),
    }, index=idx)


def _base_panel(df):
    """复刻 _dim_technical() 的原始 OHLCV 宽面板构造。"""
    return {
        "close": pd.DataFrame({SYMBOL: df["close"].values}, index=df.index),
        "high": pd.DataFrame({SYMBOL: df["high"].values}, index=df.index),
        "low": pd.DataFrame({SYMBOL: df["low"].values}, index=df.index),
        "volume": pd.DataFrame({SYMBOL: df["volume"].values}, index=df.index),
    }


def test_raw_ohlcv_panel_returns_all_50():
    """回归护栏：未注入因子帧时六维全 50（复现 P0-1 空转）。"""
    panel = _base_panel(_make_df())
    report = TechnicalAnalyzer().analyze(SYMBOL, "测试", panel)
    assert report.trend_score == 50.0
    assert report.reversal_score == 50.0
    assert report.volume_score == 50.0
    assert report.volatility_score == 50.0
    assert report.ma_score == 50.0
    assert report.limit_up_score == 50.0
    assert report.composite_score == 50.0


def test_inject_technical_factors_adds_factor_frames():
    """注入后 panel 应包含绝大多数技术因子帧，且每帧可被 _compute_factor_scores 消费。"""
    df = _make_df()
    panel = _base_panel(df)
    augmented = _inject_technical_factors(panel, df, SYMBOL)
    injected = [fid for fid in _TECH_FACTOR_IDS if fid in augmented]
    # 17 个中至少注入 15 个（turnover_anomaly 缺换手率会被 Registry 跳过）
    assert len(injected) >= 15, f"injected={len(injected)}"
    for fid in injected:
        frame = augmented[fid]
        assert isinstance(frame, pd.DataFrame)
        assert not frame.empty
        # 末行必须非全 NaN，才能被 _compute_factor_scores 读取
        assert not frame.iloc[-1].isna().all(), f"{fid} 末行为 NaN"


def test_technical_six_dim_real_scores_after_injection():
    """P0-1 核心修复验证：因子帧注入后六维不再全 50、composite 非 50。"""
    df = _make_df()
    panel = _base_panel(df)
    _inject_technical_factors(panel, df, SYMBOL)
    report = TechnicalAnalyzer().analyze(SYMBOL, "测试", panel)

    dims = [report.trend_score, report.reversal_score,
            report.volume_score, report.volatility_score, report.ma_score]
    assert any(abs(d - 50.0) > 1e-6 for d in dims), f"六维应真实打分: {dims}"
    assert abs(report.composite_score - 50.0) > 1e-6, \
        f"composite 应非 50: {report.composite_score}"
    # 至少 3 个维度显著偏离中性，证明真实因子数据进入评分而非默认兜底
    assert sum(abs(d - 50.0) > 5.0 for d in dims) >= 3, f"偏离不足: {dims}"
    # 关键六维(趋势/量价)有实际信号时不应全等
    assert not (report.trend_score == report.volume_score == 50.0)
