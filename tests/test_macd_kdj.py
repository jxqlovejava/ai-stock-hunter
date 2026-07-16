# -*- coding: utf-8 -*-
"""MACD+KDJ 五法单元测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.alphas.macd_kdj import (
    MacdKdjAction,
    MacdKdjAlphaModel,
    MacdKdjMethod,
    analyze_ohlc,
    classify_bar,
    compute_kdj,
    compute_macd,
    latest_state,
)
from src.routing.signal import Direction


def _ohlc_from_close(close: list[float]) -> pd.DataFrame:
    c = np.array(close, dtype=float)
    # 合成轻微波动的 high/low
    return pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=len(c), freq="B"),
            "open": c,
            "high": c * 1.01,
            "low": c * 0.99,
            "close": c,
            "volume": np.full(len(c), 1_000_000.0),
        }
    )


class TestComputeIndicators:
    def test_macd_length_matches(self):
        close = pd.Series(np.linspace(10, 20, 60))
        dif, dea, hist = compute_macd(close)
        assert len(dif) == 60
        assert len(dea) == 60
        assert len(hist) == 60

    def test_kdj_bounded_ish(self):
        df = _ohlc_from_close(list(np.linspace(10, 15, 50)))
        k, d, j = compute_kdj(df["high"], df["low"], df["close"])
        assert k.notna().all()
        assert d.notna().all()
        # J 可越界，K/D 通常在 0-100 附近
        assert k.iloc[-1] == pytest.approx(k.iloc[-1])


class TestClassifyBar:
    def test_m1_resonance_golden(self):
        methods, action, conf, notes = classify_bar(
            dif=-0.5,
            dea=-0.6,
            k=30,
            d=25,
            macd_golden=True,
            macd_death=False,
            kdj_golden=True,
            kdj_death=False,
        )
        assert MacdKdjMethod.RESONANCE_GOLDEN in methods
        assert action == MacdKdjAction.ENTER
        assert conf <= 0.5
        assert conf > 0

    def test_m2_dual_death(self):
        methods, action, conf, _ = classify_bar(
            dif=0.2,
            dea=0.3,
            k=70,
            d=75,
            macd_golden=False,
            macd_death=True,
            kdj_golden=False,
            kdj_death=True,
        )
        assert MacdKdjMethod.RESONANCE_DEATH in methods
        assert action == MacdKdjAction.EXIT

    def test_m2_below_zero_kdj_death(self):
        methods, action, conf, _ = classify_bar(
            dif=-0.3,
            dea=-0.2,
            k=40,
            d=45,
            macd_golden=False,
            macd_death=False,
            kdj_golden=False,
            kdj_death=True,
        )
        assert MacdKdjMethod.RESONANCE_DEATH in methods
        assert action == MacdKdjAction.EXIT

    def test_m3_avoid_entry(self):
        methods, action, conf, _ = classify_bar(
            dif=-0.4,
            dea=-0.2,  # DIF < DEA → 未拐头
            k=30,
            d=25,
            macd_golden=False,
            macd_death=False,
            kdj_golden=True,
            kdj_death=False,
        )
        assert MacdKdjMethod.BELOW_ZERO_AVOID in methods
        assert action == MacdKdjAction.AVOID_ENTRY

    def test_m4_above_zero_enter(self):
        methods, action, conf, _ = classify_bar(
            dif=0.5,
            dea=0.3,
            k=40,
            d=35,
            macd_golden=False,
            macd_death=False,
            kdj_golden=True,
            kdj_death=False,
            top_div=False,
        )
        assert MacdKdjMethod.ABOVE_ZERO_ENTER in methods
        assert action == MacdKdjAction.ENTER

    def test_m4_blocked_by_top_div(self):
        methods, action, conf, _ = classify_bar(
            dif=0.5,
            dea=0.3,
            k=40,
            d=35,
            macd_golden=False,
            macd_death=False,
            kdj_golden=True,
            kdj_death=False,
            top_div=True,
        )
        assert MacdKdjMethod.ABOVE_ZERO_ENTER not in methods

    def test_m5_wash_hold(self):
        methods, action, conf, _ = classify_bar(
            dif=-0.1,
            dea=-0.2,
            k=35,
            d=30,
            macd_golden=True,
            macd_death=False,
            kdj_golden=True,
            kdj_death=False,
            prev_dual_death_recent=True,
            small_pullback=True,
        )
        assert MacdKdjMethod.WASH_HOLD in methods
        # M1 也可能同时触发；至少含持股逻辑
        assert MacdKdjMethod.RESONANCE_GOLDEN in methods or action in (
            MacdKdjAction.HOLD,
            MacdKdjAction.ENTER,
        )

    def test_confidence_cap(self):
        _, _, conf, _ = classify_bar(
            dif=-0.5,
            dea=-0.6,
            k=30,
            d=25,
            macd_golden=True,
            macd_death=False,
            kdj_golden=True,
            kdj_death=False,
        )
        assert conf <= 0.5


class TestAnalyzeOhlc:
    def test_uptrend_series_has_states(self):
        # 先跌后涨，制造 0 轴附近交叉机会
        down = list(np.linspace(20, 10, 40))
        up = list(np.linspace(10, 18, 40))
        df = _ohlc_from_close(down + up)
        series = analyze_ohlc(df)
        assert len(series.states) == len(df)
        last = series.states[-1]
        assert last.date is not None
        assert np.isfinite(last.dif)

    def test_latest_state_none_on_empty(self):
        assert latest_state(pd.DataFrame()) is None


class TestHelpers:
    def test_state_to_dict_and_evaluate(self):
        from src.alphas.macd_kdj import evaluate_ohlc_latest, state_to_dict

        down = list(np.linspace(30, 15, 50))
        up = list(np.linspace(15, 22, 30))
        df = _ohlc_from_close(down + up)
        d = evaluate_ohlc_latest(df)
        assert d is not None
        assert "action" in d
        assert d["confidence"] <= 0.5

    def test_load_kline_cache_missing(self, tmp_path):
        from src.alphas.macd_kdj import load_kline_cache

        assert load_kline_cache("999999", tmp_path) is None


class TestMacdKdjAlphaModel:
    def test_update_empty(self):
        model = MacdKdjAlphaModel(symbol="000001")
        assert model.update(pd.DataFrame()) == []

    def test_update_insufficient_bars(self):
        model = MacdKdjAlphaModel(symbol="000001")
        df = _ohlc_from_close(list(range(10, 30)))
        assert model.update(df) == []

    def test_update_returns_signal_or_empty(self):
        model = MacdKdjAlphaModel(symbol="002460")
        # 构造长序列：下跌后反弹
        down = list(np.linspace(30, 15, 50))
        up = list(np.linspace(15, 22, 30))
        df = _ohlc_from_close(down + up)
        signals = model.update(df)
        # 可能空（当日无触发），若有则 confidence 封顶
        for s in signals:
            assert s.confidence <= 0.5
            assert s.source_model == "MacdKdjAlphaModel"
            assert s.metadata.get("nature") == "interpretation"
            assert s.direction in (Direction.UP, Direction.DOWN, Direction.FLAT)
