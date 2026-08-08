# -*- coding: utf-8 -*-
"""P1-8 高管增减持聚合 (文章共识 @LuBtc888 选股 8 标准: 高位增持=加分/一涨就减持=红旗)。

覆盖:
  aggregate_insider_trades
    ① 净增持且笔数占优 → buying
    ② 净减持且笔数占优 → selling
    ③ 增减持均衡 → neutral
    ④ 空列表 → neutral (兜底)
  ManagementEvaluator.evaluate 接入
    ⑤ buying 数据 → recent_insider_trades="buying" 且评分上浮
    ⑥ 无数据 → 保持 neutral, 评分不变

全部为纯逻辑测试, 不触发网络。
"""
from datetime import datetime

from src.data.schema import ExecutiveTrade
from src.fundamental.insider import aggregate_insider_trades
from src.fundamental.management import ManagementEvaluator


def _trade(trade_type: str, volume: int, days_ago: int = 7) -> ExecutiveTrade:
    date = (datetime.now() - __import__("datetime").timedelta(days=days_ago)).strftime("%Y-%m-%d")
    return ExecutiveTrade(executive_name="张三", trade_type=trade_type,
                          trade_date=date, volume=volume)


def test_net_buying():
    """① 净增持 + 笔数占优 → buying。"""
    trades = [_trade("buy", 10000) for _ in range(5)] + [_trade("sell", 1000)]
    out = aggregate_insider_trades(trades)
    assert out["recent_insider_trades"] == "buying"
    assert out["buy_count"] == 5 and out["sell_count"] == 1


def test_net_selling():
    """② 净减持 + 笔数占优 → selling。"""
    trades = [_trade("sell", 10000) for _ in range(5)] + [_trade("buy", 1000)]
    out = aggregate_insider_trades(trades)
    assert out["recent_insider_trades"] == "selling"


def test_balanced():
    """③ 均衡 → neutral。"""
    trades = [_trade("buy", 10000) for _ in range(2)] + [_trade("sell", 10000) for _ in range(2)]
    out = aggregate_insider_trades(trades)
    assert out["recent_insider_trades"] == "neutral"


def test_empty_fallback_neutral():
    """④ 空列表 → neutral。"""
    out = aggregate_insider_trades([])
    assert out["recent_insider_trades"] == "neutral"
    assert out["note"] == ""


def test_buying_boosts_score():
    """⑤ buying 数据 → 覆盖 insider_trades + 评分上浮 3 分。"""
    evaluator = ManagementEvaluator()
    trades = [_trade("buy", 10000) for _ in range(5)] + [_trade("sell", 1000)]
    profile = evaluator.evaluate("999999", name="未知公司", executive_trades=trades)
    assert profile.recent_insider_trades == "buying"
    assert profile.overall_score > 50.0   # 基线 50 + 3


def test_no_data_keeps_neutral():
    """⑥ 无数据 → 未知标的保持 neutral + 50 分 (零回归)。"""
    evaluator = ManagementEvaluator()
    profile = evaluator.evaluate("999999", name="未知公司", executive_trades=None)
    assert profile.recent_insider_trades == "neutral"
    assert profile.overall_score == 50.0
