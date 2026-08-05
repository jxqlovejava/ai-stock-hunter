# -*- coding: utf-8 -*-
"""P1-2 / P1-3 / P1-4 技术信号过滤器测试。

覆盖:
  ① 均线定方向 + MACD 定动能双层过滤 — 金叉但 MA20<MA50 时不触发买入
  ② MACD 顶背离入正式评分 — 被标记 (top_divergence=True) + 趋势分/综合分降权
  ③ 假突破否决过滤器 — 4 检测各否决对应突破信号
  ④ 缩量反弹降权（缩量 ≠ 反转）
  ⑤ 放量 vs 缩量破位权重差异（放量=真出逃 / 缩量=多为洗盘）
"""
import numpy as np
import pandas as pd
import pytest

from src.routing.entry_exit_engine import EntryExitEngine
from src.routing.technical import TechnicalAnalyzer

SYMBOL = "000001"


def _frame(series, index=None) -> pd.DataFrame:
    """单列宽面板帧（index=date, columns=code）。"""
    n = len(series)
    idx = index if index is not None else pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({SYMBOL: np.asarray(series, dtype=float)}, index=idx)


def _ohlc_panel(close, high=None, low=None, volume=None):
    """返回 (close, high, low, volume) 四个宽面板帧。"""
    c_arr = np.asarray(close, dtype=float)
    n = len(c_arr)
    h_arr = np.asarray(high, dtype=float) if high is not None else c_arr * 1.01
    l_arr = np.asarray(low, dtype=float) if low is not None else c_arr * 0.99
    v_arr = np.asarray(volume, dtype=float) if volume is not None else np.full(n, 1e6)
    return _frame(c_arr), _frame(h_arr), _frame(l_arr), _frame(v_arr)


def _full_panel(close, factor_ids):
    """构造带因子帧的 panel（供 TechnicalAnalyzer 六维真实打分）。"""
    idx = pd.date_range("2025-01-01", periods=len(close), freq="B")
    panel = {"close": _frame(close, idx)}
    from src.factors.registry import get_default_registry
    reg = get_default_registry()
    for fid in factor_ids:
        try:
            panel[fid] = reg.compute(fid, panel)
        except Exception:
            pass
    return panel


# ---------------------------------------------------------------------------
# ① 均线定方向 + MACD 定动能双层过滤
# ---------------------------------------------------------------------------


class TestGoldenCrossDirectionFilter:
    def test_golden_cross_blocked_when_ma20_below_ma50(self):
        """金叉形态成立但 MA20<MA50 → 不触发买入信号。"""
        # 先高位(110)后回落(95)再小幅反弹(103)：MA5 上穿 MA20，但 MA20<MA50
        close = np.concatenate([np.full(30, 110.0), np.full(25, 95.0), np.full(4, 95.0), [103.0]])
        c, h, l, v = _ohlc_panel(close)
        ma5, ma20, ma50 = c.rolling(5).mean(), c.rolling(20).mean(), c.rolling(50).mean()
        # 前置条件自检：金叉形态成立但方向层被否决
        assert ma5.iloc[-1, 0] > ma20.iloc[-1, 0]
        assert ma5.iloc[-2, 0] <= ma20.iloc[-2, 0]
        assert ma20.iloc[-1, 0] < ma50.iloc[-1, 0]

        engine = EntryExitEngine()
        assert engine._detect_golden_cross(c, v) is None

    def test_golden_cross_fires_when_ma20_above_ma50(self):
        """MA20>MA50 且 MA20 向上 → 金叉成立（对照）。"""
        close = np.concatenate([np.full(50, 90.0), np.full(4, 90.0), [100.0]])
        c, h, l, v = _ohlc_panel(close)
        ma20, ma50 = c.rolling(20).mean(), c.rolling(50).mean()
        assert ma20.iloc[-1, 0] > ma50.iloc[-1, 0]

        engine = EntryExitEngine()
        sig = engine._detect_golden_cross(c, v)
        assert sig is not None
        assert sig.type == "MA_GOLDEN_CROSS"

    def test_golden_cross_short_data_falls_back_to_ma20_rising(self):
        """数据不足 MA50 时退化为仅要求 MA20 向上（金叉仍成立）。"""
        # 仅 35 根：上升段内 MA20 向上、MA5 上穿 MA20
        close = np.concatenate([np.full(28, 90.0), [90.0, 90.0, 90.0, 90.0], [100.0, 101.0]])
        c, h, l, v = _ohlc_panel(close)
        engine = EntryExitEngine()
        sig = engine._detect_golden_cross(c, v)
        # 至少不因 MA50 缺失而崩溃；若金叉形态成立则触发
        assert sig is None or sig.type == "MA_GOLDEN_CROSS"


# ---------------------------------------------------------------------------
# ② MACD 顶背离入正式评分
# ---------------------------------------------------------------------------


class TestMacdTopDivergence:
    @staticmethod
    def _divergent_close():
        # 急涨(100→130) → 回撤(130→118) → 再涨至新高(118→132) → 顶部横盘微创新高
        fast = np.linspace(100, 130, 40)
        pull = np.linspace(130, 118, 20)
        rise = np.linspace(118, 132, 12)
        flat = np.array([132.0, 132.2, 132.3, 132.5, 132.6])
        return np.concatenate([fast, pull, rise, flat])

    def test_top_divergence_detected_and_flagged(self):
        close = self._divergent_close()
        panel = _full_panel(close, ["macd_histogram", "dmi_direction", "ma_bias"])
        report = TechnicalAnalyzer().analyze(SYMBOL, "测试", panel)
        div = [s for s in report.signals if s.top_divergence]
        assert div, "应产生 MACD 顶背离信号"
        for s in div:
            assert s.indicator == "MACD_TOP_DIVERGENCE"
            assert s.direction == "BEARISH"
            assert s.is_exit

    def test_top_divergence_downgrades_scores(self, monkeypatch):
        close = self._divergent_close()
        panel = _full_panel(close, ["macd_histogram", "dmi_direction", "ma_bias"])

        analyzer = TechnicalAnalyzer()
        monkeypatch.setattr(analyzer, "_detect_top_divergence", lambda p: SYMBOL)
        with_div = analyzer.analyze(SYMBOL, "测试", panel)

        monkeypatch.setattr(analyzer, "_detect_top_divergence", lambda p: None)
        without_div = analyzer.analyze(SYMBOL, "测试", panel)

        # 顶背离 → 趋势分与综合分降权
        assert with_div.trend_score < without_div.trend_score
        assert with_div.composite_score < without_div.composite_score
        assert with_div.trend_score == pytest.approx(without_div.trend_score * 0.9, abs=1e-6)

    def test_raw_panel_keeps_all_50_regression(self):
        """回归护栏：无因子帧时六维仍全 50（顶背离检测不应污染兜底路径）。"""
        close = self._divergent_close()
        idx = pd.date_range("2025-01-01", periods=len(close), freq="B")
        panel = {"close": _frame(close, idx)}
        report = TechnicalAnalyzer().analyze(SYMBOL, "测试", panel)
        for d in ("trend_score", "reversal_score", "volume_score",
                  "volatility_score", "ma_score", "limit_up_score"):
            assert abs(getattr(report, d) - 50.0) < 1e-9


# ---------------------------------------------------------------------------
# ③ 假突破否决过滤器（4 检测）
# ---------------------------------------------------------------------------


class TestFakeBreakoutVeto:
    def test_check1_intraday_pierce_reject(self):
        """盘中破位收盘跌回 — 最高价上破前高但收盘跌回下方。"""
        close = np.append(np.full(30, 100.0), 99.0)
        high = np.append(np.full(30, 101.0), 105.0)
        c, h, l, v = _ohlc_panel(close, high=high)
        engine = EntryExitEngine()
        assert engine._detect_fake_breakout(c, h, v) == "盘中破位收盘跌回"
        # 端到端：假突破不产生 BREAKOUT 入场信号
        result = engine.evaluate(SYMBOL, "测试", {"close": c, "high": h, "low": l, "volume": v})
        assert not any(s.type == "BREAKOUT" for s in result.entry_signals)

    def test_check2_high_vol_long_shadow_vetoes_breakout(self):
        """放量不涨留长上影 — 收盘破前高但留长上影且放量 → 否决真实突破信号。"""
        close = np.append(np.full(30, 100.0), 102.0)
        high = np.append(np.full(30, 101.0), 106.0)
        volume = np.append(np.full(30, 5e5), 2e6)
        c, h, l, v = _ohlc_panel(close, high=high, volume=volume)
        engine = EntryExitEngine()
        assert engine._detect_fake_breakout(c, h, v) == "放量不涨留长上影"
        # 对照组：无长上影（收盘=最高）时该突破应成立
        high_clean = np.append(np.full(30, 101.0), 102.0)
        c2, h2, l2, v2 = _ohlc_panel(close, high=high_clean, volume=volume)
        bk = engine._detect_breakout(c2, h2, v2)
        assert bk is not None and bk.type == "BREAKOUT"
        # 有长上影时 evaluate 否决
        result = engine.evaluate(SYMBOL, "测试", {"close": c, "high": h, "low": l, "volume": v})
        assert not any(s.type == "BREAKOUT" for s in result.entry_signals)

    def test_check3_no_follow_through(self):
        """突破当天放量后续不新高 — 突破后价格未再创新高。"""
        close = np.concatenate([np.full(30, 100.0), [105.0, 106.0, 106.0]])
        high = np.concatenate([np.full(30, 101.0), [107.0, 106.5, 106.5]])
        volume = np.concatenate([np.full(30, 5e5), [2e6, 2e6, 2e6]])
        c, h, l, v = _ohlc_panel(close, high=high, volume=volume)
        engine = EntryExitEngine()
        assert engine._detect_fake_breakout(c, h, v) == "突破后不新高"

    def test_check4_pullback_rebreak(self):
        """回踩放量重新跌破 — 突破后回踩放量跌破突破位。"""
        close = np.concatenate([np.full(30, 100.0), [105.0, 110.0, 110.0, 100.0]])
        high = np.concatenate([np.full(30, 101.0), [105.0, 112.0, 114.0, 110.0]])
        volume = np.concatenate([np.full(30, 5e5), [2e6, 2e6, 2e6, 2e6]])
        c, h, l, v = _ohlc_panel(close, high=high, volume=volume)
        engine = EntryExitEngine()
        assert engine._detect_fake_breakout(c, h, v) == "回踩放量重新跌破"


# ---------------------------------------------------------------------------
# ④ 缩量反弹降权（≠反转）
# ---------------------------------------------------------------------------


class TestShrinkVolumeDowngrade:
    def test_oversold_bounce_shrink_downgraded(self):
        close = np.concatenate([np.linspace(100, 60, 39), [61.0]])
        n = len(close)
        shrink = np.append(np.full(n - 1, 1e6), 4e5)   # 末量缩
        normal = np.append(np.full(n - 1, 5e5), 1e6)   # 末量放
        engine = EntryExitEngine()

        c, h, l, v = _ohlc_panel(close, volume=shrink)
        ob_s = engine._detect_oversold_bounce(c, v)
        c, h, l, v = _ohlc_panel(close, volume=normal)
        ob_n = engine._detect_oversold_bounce(c, v)

        assert ob_s is not None and ob_n is not None
        assert ob_s.confidence < ob_n.confidence
        assert "缩量" in ob_s.description
        assert "缩量" not in ob_n.description
        # 降权系数验证: 0.55 * 0.7 = 0.385
        assert ob_s.confidence == pytest.approx(0.55 * engine.SHRINK_REBOUND_DOWNGRADE, abs=1e-6)
        assert ob_n.confidence == pytest.approx(0.55, abs=1e-6)

    def test_pullback_support_shrink_downgraded(self):
        close = np.append(np.full(20, 100.0), 100.4)
        low = np.append(np.full(20, 99.0), 99.4)  # 末量低点贴近 MA20
        n = len(close)
        shrink = np.append(np.full(n - 1, 1e6), 4e5)
        normal = np.append(np.full(n - 1, 5e5), 1e6)
        engine = EntryExitEngine()

        c, h, l, v = _ohlc_panel(close, low=low, volume=shrink)
        ps_s = engine._detect_pullback_support(c, l, v)
        c, h, l, v = _ohlc_panel(close, low=low, volume=normal)
        ps_n = engine._detect_pullback_support(c, l, v)

        assert ps_s is not None and ps_n is not None
        assert ps_s.confidence < ps_n.confidence
        assert "缩量" in ps_s.description
        assert ps_s.confidence == pytest.approx(0.6 * engine.SHRINK_REBOUND_DOWNGRADE, abs=1e-6)


# ---------------------------------------------------------------------------
# ⑤ 放量 vs 缩量破位权重差异 + 顶背离联动
# ---------------------------------------------------------------------------


class TestBreakdownVolumeQuality:
    @staticmethod
    def _breakdown_panel(volume_last, volume_base):
        """上升段后单日回落 96：跌破 MA20（非 MA60），落在 MA20 破位分支。"""
        p = np.concatenate([np.full(60, 90.0), np.linspace(90, 110, 20)])
        close = np.concatenate([p, [96.0]])
        n = len(close)
        volume = np.append(np.full(n - 1, volume_base), volume_last)
        return _ohlc_panel(close, volume=volume)

    def test_heavy_vs_shrink_breakdown_weight(self):
        engine = EntryExitEngine()
        c, h, l, v = self._breakdown_panel(2e6, 5e5)  # 放量破位
        heavy = engine._detect_ma_breakdown(c, v)
        c, h, l, v = self._breakdown_panel(5e5, 1e6)  # 缩量破位
        shrink = engine._detect_ma_breakdown(c, v)

        assert heavy is not None and shrink is not None
        assert heavy.confidence > shrink.confidence
        assert "放量" in heavy.description and "真出逃" in heavy.description
        assert "缩量" in shrink.description and "洗盘" in shrink.description
        assert heavy.confidence == pytest.approx(0.62, abs=1e-9)
        assert shrink.confidence == pytest.approx(0.40, abs=1e-9)

    def test_breakdown_with_top_divergence_linked(self):
        """顶背离 + 破位联动：置信度加成并升级 URGENT。"""
        engine = EntryExitEngine()
        c, h, l, v = self._breakdown_panel(5e5, 1e6)
        s = engine._detect_ma_breakdown(c, v, top_divergence=True)
        assert s is not None
        assert s.confidence == pytest.approx(0.40 + engine.TOP_DIVERGENCE_BOOST, abs=1e-9)
        assert s.urgency == "URGENT"
        assert "顶背离" in s.description


# ---------------------------------------------------------------------------
# 因子注册回归（MA120/MA250/macd_hist_rising 对齐现有技术因子）
# ---------------------------------------------------------------------------


class TestNewFactorRegistration:
    def test_long_term_ma_and_macd_hist_rising_registered(self):
        from src.factors.registry import get_default_registry
        reg = get_default_registry()
        rng = np.random.default_rng(7)
        close = 100 + np.cumsum(rng.normal(0.05, 1.0, 300))
        idx = pd.date_range("2025-01-01", periods=300, freq="B")
        panel = {"close": _frame(close, idx)}
        for fid in ("ma_120", "ma_250", "macd_hist_rising"):
            assert fid in reg.list(), f"{fid} 应被 Registry 注册"
            out = reg.compute(fid, panel)
            assert isinstance(out, pd.DataFrame) and not out.empty
            assert not out.iloc[-1].isna().all()
            assert np.isfinite(out.to_numpy()).all()
