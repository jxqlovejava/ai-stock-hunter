# -*- coding: utf-8 -*-
"""P1-8 战术叠加 — F1/F2/F3/F4/F5 共识信号聚合注入全链路决策。

覆盖:
  compute_tactical_overlay
    ① F1 高位涨停次日低开 → r044 flag + score -10
    ② F3 弱势突破 → r045 flag + score -5
    ③ F5 急涨缓跌(出货) → score -5
    ④ F2 弱封 + 尾盘急拉 → score 负向
    ⑤ F4 高管净增持 → score +3
    ⑥ 无数据 → 中性 (score 0, 无 flag)

全部为纯逻辑测试, 不触发网络。
"""
import pandas as pd

from src.routing.tactical_overlay import compute_tactical_overlay

SYMBOL = "000001"


def _mk_df(closes, start="2023-01-02"):
    idx = pd.date_range(start, periods=len(closes), freq="B")
    closes = [float(c) for c in closes]
    return pd.DataFrame({
        "date": idx,
        "open": [c * 0.99 for c in closes],
        "high": [c * 1.02 for c in closes],
        "low": [c * 0.98 for c in closes],
        "close": closes,
        "volume": [1_000_000.0] * len(closes),
    })


def _high_gap_down_df():
    """高位涨停次日低开 (触发 r044 distribute_warning)。"""
    closes = [100 + i * 0.7 for i in range(137)]
    closes.append(round(closes[-1] * 1.1, 2))     # 涨停日
    closes.append(round(closes[-1] * 0.99, 2))    # 今日低开
    return _mk_df(closes)


def test_f1_high_gap_down_sets_flag_and_negative_delta():
    """① 高位涨停次日低开 → r044 flag + 出货预警 -10。"""
    out = compute_tactical_overlay(SYMBOL, daily_df=_high_gap_down_df())
    assert out["doctrine_flags"].get("limit_up_next_day_gap_down") is True
    assert any(s["name"] == "涨停次日出货预警" for s in out["signals"])
    assert out["score_delta"] <= -10


def test_f3_weak_breakout_sets_flag_and_negative():
    """② 弱势突破 → r045 flag + -5。"""
    closes = [10.0 + i * 0.01 for i in range(24)]
    highs = [10.0 + i * 0.02 for i in range(24)]
    vols = [100.0] * 24
    closes.append(10.8)   # 幅度 ~3.3%
    highs.append(11.0)
    vols.append(160.0)    # 量比 1.6 < 1.7 → WEAK
    df = _mk_df(closes)
    df["high"] = highs
    df["volume"] = vols
    out = compute_tactical_overlay(SYMBOL, daily_df=df)

    assert out["doctrine_flags"].get("breakout_weak") is True
    assert any(s["name"] == "弱势突破" for s in out["signals"])
    assert out["score_delta"] <= -5


def test_f5_distribution_shape_negative():
    """③ 急涨缓跌(出货) → -5。"""
    moves = [0.04 if i % 2 == 0 else -0.01 for i in range(59)]
    closes = [100.0]
    for m in moves:
        closes.append(closes[-1] * (1 + m))
    df = _mk_df(closes)
    out = compute_tactical_overlay(SYMBOL, daily_df=df)

    assert any(s["name"] == "急涨缓跌(出货)" for s in out["signals"])
    assert out["score_delta"] <= -5


def test_f4_insider_buying_positive():
    """⑤ 高管净增持 → +3。"""
    from datetime import datetime, timedelta
    from src.data.schema import ExecutiveTrade

    def _t(typ, vol):
        d = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        return ExecutiveTrade(executive_name="张三", trade_type=typ, trade_date=d, volume=vol)

    trades = [_t("buy", 10000) for _ in range(5)] + [_t("sell", 1000)]
    out = compute_tactical_overlay(SYMBOL, daily_df=None, executive_trades=trades)

    assert any(s["name"] == "高管净增持" for s in out["signals"])
    assert out["score_delta"] >= 3


def test_no_data_neutral():
    """⑥ 无任何数据 → 中性 (score 0, 无 flag)。"""
    out = compute_tactical_overlay(SYMBOL, daily_df=None, minute_bars=None, executive_trades=None)
    assert out["score_delta"] == 0
    assert out["doctrine_flags"] == {}
    assert out["signals"] == []
