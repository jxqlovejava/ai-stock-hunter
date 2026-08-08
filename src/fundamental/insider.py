# -*- coding: utf-8 -*-
"""高管增减持聚合 — 把 ExecutiveTrade 列表压缩为 insider 信号。

文章共识 @LuBtc888 (知乎选股 8 标准): 管理层愿意在股价高位继续增持=加分,
一涨就疯狂减持套现=红旗。数据源: aggregator.get_executive_trades
(mx-data → 东财 RPT_EXECUTIVE_TRADE)，本模块做纯逻辑聚合，可独立单测。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 近 6 个月统计窗口
_INSIDER_WINDOW_DAYS = 180


def aggregate_insider_trades(executive_trades: list) -> dict:
    """聚合高管增减持 → {recent_insider_trades, note, net_volume, buy_count, sell_count}。

    recent_insider_trades: "buying" / "selling" / "neutral"。

    判定规则（净额显著 + 笔数对比，防单笔噪音）:
      - 净买入 > 0 且 增持笔数 ≥ 减持笔数 × 1.5  → "buying"
      - 净卖出 < 0 且 减持笔数 ≥ 增持笔数 × 1.5  → "selling"
      - 其余                                  → "neutral"
    """
    out = {
        "recent_insider_trades": "neutral",
        "note": "",
        "net_volume": 0,
        "buy_count": 0,
        "sell_count": 0,
    }
    if not executive_trades:
        return out

    cutoff = datetime.now() - timedelta(days=_INSIDER_WINDOW_DAYS)
    buy_vol = 0
    sell_vol = 0
    buy_count = 0
    sell_count = 0

    for t in executive_trades:
        try:
            d = getattr(t, "trade_date", "") or ""
            if d:
                td = datetime.strptime(str(d)[:10], "%Y-%m-%d")
                if td < cutoff:
                    continue
        except Exception:
            pass  # 日期缺失/格式异常 → 不因日期丢弃该笔

        typ = str(getattr(t, "trade_type", "") or "").lower()
        try:
            vol = int(getattr(t, "volume", None) or 0)
        except (ValueError, TypeError):
            vol = 0
        if "sell" in typ or "减" in typ:
            sell_vol += abs(vol)
            sell_count += 1
        elif "buy" in typ or "增" in typ:
            buy_vol += abs(vol)
            buy_count += 1
        else:
            continue  # 未知类型不计数

    net = buy_vol - sell_vol
    out["net_volume"] = net
    out["buy_count"] = buy_count
    out["sell_count"] = sell_count

    if buy_count == 0 and sell_count == 0:
        return out

    if net > 0 and buy_count >= sell_count * 1.5:
        out["recent_insider_trades"] = "buying"
        out["note"] = f"近6个月高管净增持{buy_count}笔 vs 减持{sell_count}笔 (净额 {net:,}股)"
    elif net < 0 and sell_count >= buy_count * 1.5:
        out["recent_insider_trades"] = "selling"
        out["note"] = f"近6个月高管净减持{sell_count}笔 vs 增持{buy_count}笔 (净额 {net:,}股)"
    else:
        out["note"] = f"近6个月高管增减持均衡 (增{buy_count}笔/减{sell_count}笔)"
    return out
