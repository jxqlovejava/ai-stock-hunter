# -*- coding: utf-8 -*-
"""盘口与分时数据模块。

借鉴 go-stock 盘口数据解析（东财实时行情），提供：
- 买卖五档盘口 (OrderBookSnapshot)
- 分时成交数据 (IntradaySnapshot)
- 买卖力度比计算

用于 L3 建仓时机的盘口信号判断。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import requests

from src.data.source_citation import (
    SOURCE_TIER_T1,
    NATURE_FACT,
    SourceCitation,
    make_citation,
)

logger = logging.getLogger(__name__)

# 东财 API 直连 Session（绕过系统代理如 Clash，避免 ProxyError）
_EM_SESSION = requests.Session()
_EM_SESSION.trust_env = False
_EM_SESSION.proxies = {"http": None, "https": None}
_EM_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
})

# 东财个股实时行情 API（含五档盘口）
_EM_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
_EM_FIELDS = (
    "f43,f44,f45,f46,f47,f48,f50,f51,f52,f55,f57,f58,f60,f116,f117,"
    "f19,f20,f21,f22,f23,f24,f25,f26,f27,f28,f29,f30,f31,f32,"
    "f33,f34,f35,f36,f37,f38,f39,f40,f162,f167,f168,f169,f170,f171"
)
_REQUEST_TIMEOUT = 10.0


# ── 数据模型 ────────────────────────────────────────────────────────────


@dataclass
class OrderBookSnapshot:
    """五档盘口快照。"""
    symbol: str = ""
    name: str = ""

    # 买盘 (bid)
    bid1_price: float = 0.0
    bid1_vol: int = 0
    bid2_price: float = 0.0
    bid2_vol: int = 0
    bid3_price: float = 0.0
    bid3_vol: int = 0
    bid4_price: float = 0.0
    bid4_vol: int = 0
    bid5_price: float = 0.0
    bid5_vol: int = 0

    # 卖盘 (ask)
    ask1_price: float = 0.0
    ask1_vol: int = 0
    ask2_price: float = 0.0
    ask2_vol: int = 0
    ask3_price: float = 0.0
    ask3_vol: int = 0
    ask4_price: float = 0.0
    ask4_vol: int = 0
    ask5_price: float = 0.0
    ask5_vol: int = 0

    # 辅助
    current_price: float = 0.0
    change_pct: float = 0.0
    timestamp: str = ""

    # 计算字段
    bid_total_vol: int = 0      # 买五档总挂单量
    ask_total_vol: int = 0      # 卖五档总挂单量
    bid_ask_ratio: float = 1.0  # 买卖力度比 (买盘/卖盘)
    signal: str = "neutral"     # bullish / bearish / neutral

    error: Optional[str] = None
    source: str = ""


@dataclass
class IntradaySnapshot:
    """分时成交快照。"""
    symbol: str = ""
    time: str = ""        # HH:MM
    price: float = 0.0
    volume: int = 0       # 成交量（手）
    amount: float = 0.0   # 成交额
    avg_price: float = 0.0  # 均价
    change_pct: float = 0.0


# ── 数据获取器 ──────────────────────────────────────────────────────────


class OrderBookFetcher:
    """东财五档盘口数据获取器。"""

    @staticmethod
    def _to_secid(symbol: str) -> str:
        """纯数字代码 → 东财 secid（1=沪，0=深）。"""
        code = symbol.strip()[-6:]
        if len(code) != 6 or not code.isdigit():
            raise ValueError(f"无效股票代码: {symbol}")
        first = code[0]
        market = "1" if first in ("6", "9") else "0"
        return f"{market}.{code}"

    @staticmethod
    def fetch(symbol: str) -> OrderBookSnapshot:
        """获取个股五档盘口数据。

        Args:
            symbol: 股票代码（6位纯数字）

        Returns:
            OrderBookSnapshot，包含买卖五档明细 + 买卖力度比
        """
        try:
            secid = OrderBookFetcher._to_secid(symbol)
        except ValueError as e:
            return OrderBookSnapshot(symbol=symbol, error=str(e), source="N/A")

        url = (
            f"{_EM_QUOTE_URL}?secid={secid}"
            f"&fields={_EM_FIELDS}"
            f"&ut=7eea3edcaed734bea9cbfc24409ed989"
            f"&_={int(time.time() * 1000)}"
        )

        try:
            resp = _EM_SESSION.get(
                url,
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            return OrderBookSnapshot(
                symbol=symbol, error=str(e), source="东财 push2"
            )

        try:
            payload = resp.json()
        except ValueError:
            return OrderBookSnapshot(
                symbol=symbol, error="API 返回非 JSON", source="东财 push2"
            )

        if not isinstance(payload, dict):
            return OrderBookSnapshot(
                symbol=symbol, error="API 数据结构异常", source="东财 push2"
            )

        data = payload.get("data", {})
        if not data:
            return OrderBookSnapshot(
                symbol=symbol, error="无盘口数据（可能非交易时间）", source="东财 push2"
            )

        # 解析五档
        bid1_p = float(data.get("f19", 0) or 0)
        bid1_v = int(data.get("f20", 0) or 0)
        bid2_p = float(data.get("f21", 0) or 0)
        bid2_v = int(data.get("f22", 0) or 0)
        bid3_p = float(data.get("f23", 0) or 0)
        bid3_v = int(data.get("f24", 0) or 0)
        bid4_p = float(data.get("f25", 0) or 0)
        bid4_v = int(data.get("f26", 0) or 0)
        bid5_p = float(data.get("f27", 0) or 0)
        bid5_v = int(data.get("f28", 0) or 0)

        ask1_p = float(data.get("f29", 0) or 0)
        ask1_v = int(data.get("f30", 0) or 0)
        ask2_p = float(data.get("f31", 0) or 0)
        ask2_v = int(data.get("f32", 0) or 0)
        ask3_p = float(data.get("f33", 0) or 0)
        ask3_v = int(data.get("f34", 0) or 0)
        ask4_p = float(data.get("f35", 0) or 0)
        ask4_v = int(data.get("f36", 0) or 0)
        ask5_p = float(data.get("f37", 0) or 0)
        ask5_v = int(data.get("f38", 0) or 0)

        bid_total = bid1_v + bid2_v + bid3_v + bid4_v + bid5_v
        ask_total = ask1_v + ask2_v + ask3_v + ask4_v + ask5_v

        # 买卖力度比
        bid_ask_ratio = bid_total / max(ask_total, 1)

        # 信号判定
        signal = "neutral"
        if bid_ask_ratio >= 2.0:
            signal = "bullish"       # 买盘远超卖盘
        elif bid_ask_ratio >= 1.5:
            signal = "slightly_bullish"
        elif bid_ask_ratio <= 0.5:
            signal = "bearish"       # 卖盘远超买盘
        elif bid_ask_ratio <= 0.67:
            signal = "slightly_bearish"

        return OrderBookSnapshot(
            symbol=symbol,
            name=str(data.get("f58", "")),
            bid1_price=bid1_p, bid1_vol=bid1_v,
            bid2_price=bid2_p, bid2_vol=bid2_v,
            bid3_price=bid3_p, bid3_vol=bid3_v,
            bid4_price=bid4_p, bid4_vol=bid4_v,
            bid5_price=bid5_p, bid5_vol=bid5_v,
            ask1_price=ask1_p, ask1_vol=ask1_v,
            ask2_price=ask2_p, ask2_vol=ask2_v,
            ask3_price=ask3_p, ask3_vol=ask3_v,
            ask4_price=ask4_p, ask4_vol=ask4_v,
            ask5_price=ask5_p, ask5_vol=ask5_v,
            current_price=float(data.get("f43", 0) or 0),
            change_pct=float(data.get("f170", 0) or data.get("f169", 0) or 0),
            timestamp=datetime.now().isoformat(),
            bid_total_vol=bid_total,
            ask_total_vol=ask_total,
            bid_ask_ratio=round(bid_ask_ratio, 2),
            signal=signal,
            source="东财 push2",
        )


# ── 盘口力度分析 ────────────────────────────────────────────────────────


def compute_bid_strength(ob: OrderBookSnapshot) -> dict:
    """计算盘口买卖力度指标，供 L3 仓位调度使用。

    Returns dict with:
        - bid_ask_ratio: 买卖力度比
        - bid_ask_imbalance: 盘口失衡度 (bid - ask) / (bid + ask)
        - spread_pct: 买卖价差率 (ask1 - bid1) / bid1 × 100
        - depth_signal: deep_buy / strong_buy / neutral / strong_sell / deep_sell
        - confidence: 盘口信号可信度 (0-1)
    """
    if ob.error:
        return {"depth_signal": "no_data", "confidence": 0.0}

    ratio = ob.bid_ask_ratio
    imbalance = (ob.bid_total_vol - ob.ask_total_vol) / max(
        ob.bid_total_vol + ob.ask_total_vol, 1
    )

    # 价差率
    spread_pct = 0.0
    if ob.bid1_price > 0 and ob.ask1_price > 0:
        spread_pct = (ob.ask1_price - ob.bid1_price) / ob.bid1_price * 100

    # 深度信号
    if ratio >= 2.0:
        depth = "deep_buy"
        conf = 0.85
    elif ratio >= 1.5:
        depth = "strong_buy"
        conf = 0.75
    elif ratio >= 1.2:
        depth = "slight_buy"
        conf = 0.55
    elif ratio <= 0.5:
        depth = "deep_sell"
        conf = 0.85
    elif ratio <= 0.67:
        depth = "strong_sell"
        conf = 0.75
    elif ratio <= 0.83:
        depth = "slight_sell"
        conf = 0.55
    else:
        depth = "neutral"
        conf = 0.4

    # 价差过大降低可信度
    if spread_pct > 1.0:
        conf *= 0.8

    return {
        "bid_ask_ratio": round(ratio, 2),
        "bid_ask_imbalance": round(imbalance, 3),
        "spread_pct": round(spread_pct, 3),
        "depth_signal": depth,
        "confidence": round(conf, 2),
    }
