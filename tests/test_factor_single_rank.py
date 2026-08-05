# -*- coding: utf-8 -*-
"""单票面板 rank 因子恒 100 → ts_rank 变体 修复验证。

背景: 截面 rank(axis=1) 在单列面板（单只股票）下每行唯一值 rank=1.0 → 因子恒 100，
推高趋势/反转/均线维度，技术评分失真。
修复: base.cross_or_ts_rank 对单列面板回退到时序 rank（当前值 vs 自身回看窗口分位），
多列面板保持截面 rank 不变。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.factors.base import cross_or_ts_rank, rank, ts_rank_value
from src.factors.registry import get_default_registry

SINGLE_COL_FACTORS = [
    "macd_histogram",        # 趋势
    "dmi_direction",         # 趋势
    "short_term_reversal",   # 反转
    "obv_divergence",        # 量能
    "ma_alignment",          # 均线
    "ma_cross",              # 均线
]

SYMBOL = "000001"
N = 300


def _single_col_panel(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """单列宽面板: index=date, columns=[SYMBOL]（复刻 tactics 单票场景）。"""
    idx = df.index
    return {
        k: pd.DataFrame({SYMBOL: df[k].values}, index=idx)
        for k in ("close", "high", "low", "volume")
    }


def _random_walk_df(n=N, seed=7):
    """带温和漂移的随机游走 K 线，保证因子时序值真实变化。"""
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


class TestCrossOrTsRankDispatch:
    """cross_or_ts_rank 自动路由: 多列走截面 rank，单列走时序 rank。"""

    def test_multi_column_matches_cross_section(self):
        df = pd.DataFrame({"A": [1.0, 3.0], "B": [2.0, 1.0], "C": [3.0, 2.0]})
        out = cross_or_ts_rank(df, n=2)
        # 多列行为与之前完全一致（向后兼容）
        pd.testing.assert_frame_equal(out, rank(df))
        # 截面语义保留: 每行内跨列排名 pct
        assert out.iloc[0].tolist() == pytest.approx([1 / 3, 2 / 3, 1.0])

    def test_single_column_matches_ts(self):
        df = pd.DataFrame({"A": [1.0, 2.0, 3.0, 2.5]})
        out = cross_or_ts_rank(df, n=2)
        pd.testing.assert_frame_equal(out, ts_rank_value(df, n=2))
        # 单列不再恒 1.0: 末值 2.5 在窗口 [3.0, 2.5] 中非最大 → 0.5 < 1.0
        assert out.iloc[-1, 0] == pytest.approx(0.5)
        # 冷启动单值窗口（仅自身）→ 1.0（与 ts_rank/rank 语义一致）
        assert out.iloc[0, 0] == pytest.approx(1.0)

    def test_single_column_pct_in_unit_range(self):
        df = pd.DataFrame({"A": [1.0, 5.0, 3.0, 4.0, 2.0, 6.0]})
        out = cross_or_ts_rank(df, n=6)
        vals = out["A"].dropna()
        assert ((vals >= 0.0) & (vals <= 1.0)).all()


class TestTsRankValueNaNDefense:
    """ts_rank_value 的 NaN 防御与最小窗口。"""

    def test_all_nan_window(self):
        df = pd.DataFrame({"A": [np.nan, np.nan, np.nan]})
        out = ts_rank_value(df, n=2)
        assert out.isna().all().all()

    def test_nan_last_value(self):
        df = pd.DataFrame({"A": [1.0, 2.0, np.nan]})
        out = ts_rank_value(df, n=3)
        assert np.isnan(out.iloc[-1, 0])       # 末值 NaN → 该点 NaN（不伪装 0 分）
        assert not np.isnan(out.iloc[1, 0])    # 中间有限值仍计算

    def test_nan_middle_skipped(self):
        df = pd.DataFrame({"A": [1.0, np.nan, 3.0, 4.0]})
        out = ts_rank_value(df, n=3)
        # 窗口 [nan, 3, 4] 内末值 4 为有限值最大 → 1.0（NaN 自动剔除）
        assert out.iloc[-1, 0] == pytest.approx(1.0)

    def test_short_series_min_window_no_error(self):
        df = pd.DataFrame({"A": [5.0, 6.0]})
        out = ts_rank_value(df, n=20)
        assert out.shape == df.shape
        # 窗口不足 n 时按已有数据计算，不报错；末值 6 为窗口最大 → 1.0
        assert out.iloc[-1, 0] == pytest.approx(1.0)


class TestSingleColumnFactorsNotConstant100:
    """核心修复: 6 个受影响因子在单列面板下输出非恒 100。"""

    @pytest.fixture(params=SINGLE_COL_FACTORS)
    def factor_id(self, request):
        return request.param

    def test_single_column_not_constant_100(self, factor_id):
        panel = _single_col_panel(_random_walk_df())
        out = get_default_registry().compute(factor_id, panel)
        assert out.shape[1] == 1, f"{factor_id} 应为单列输出"

        last = float(out.iloc[-1, 0])
        assert np.isfinite(last), f"{factor_id} 末行为 NaN"
        assert 0.0 < last <= 100.0, f"{factor_id} 末行越界: {last}"

        tail = out.iloc[-100:, 0].dropna()
        assert len(tail) > 0, f"{factor_id} 尾部全 NaN"
        # 非恒 100 失真: 尾部存在 < 100 的值，且值有真实变化
        assert (tail < 100.0).any(), f"{factor_id} 尾部仍恒 100"
        assert tail.nunique() > 5, f"{factor_id} 尾部值几乎无变化: {sorted(tail.unique())}"


class TestMultiColumnKeepsCrossSectional:
    """回归: 多列面板仍走截面 rank，行为与之前一致。"""

    def test_macd_histogram_multi_column(self):
        idx = pd.date_range("2025-01-01", periods=200, freq="B")
        close = pd.DataFrame({
            "A": np.linspace(100, 300, 200),   # 上升 → MACD 正柱（行内最强）
            "B": np.full(200, 200.0),          # 持平 → 柱≈0（行内居中）
            "C": np.linspace(300, 100, 200),   # 下降 → MACD 负柱（行内最弱）
        }, index=idx)
        panel = {"close": close}
        out = get_default_registry().compute("macd_histogram", panel)

        last = out.iloc[-1]
        # 截面 rank 语义保留: 每行最强列恒 100，其余按跨列排名递减
        assert last["A"] == pytest.approx(100.0, abs=1e-9)
        assert last["A"] > last["B"] > last["C"]
        assert last["C"] < 50.0
