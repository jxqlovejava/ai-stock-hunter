# -*- coding: utf-8 -*-
"""美股隔夜大盘数据获取模块。

通过东方财富全球指数 API 免费获取 S&P 500 / Nasdaq / Dow Jones 隔夜收盘数据，
用于 A 股分析 pipeline 的宏观情绪修正。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from time import sleep
from typing import Optional

try:
    from curl_cffi import requests
except ImportError:  # pragma: no cover
    import requests  # type: ignore[no-redef]

from src.data.source_citation import SourceCitation, make_citation

logger = logging.getLogger(__name__)


# 东方财富全球指数 API 代码映射
# key: API 返回的 f12 字段; value: (内部 symbol, 显示名称)
EASTMONEY_US_INDICES: dict[str, tuple[str, str]] = {
    "SPX": ("^GSPC", "S&P 500"),
    "NDX": ("^IXIC", "Nasdaq Composite"),
    "DJIA": ("^DJI", "Dow Jones Industrial Average"),
}

EASTMONEY_US_API_URL = (
    "https://push2.eastmoney.com/api/qt/ulist.np/get"
    "?fltt=2&invt=2&fields=f12,f13,f14,f2,f3,f4,f18"
    "&secids=100.SPX,100.NDX,100.DJIA"
)


@dataclass(frozen=True)
class USIndexSnapshot:
    """单个美股指数的隔夜收盘快照。"""

    symbol: str
    name: str
    trade_date: date
    close: float
    prev_close: float
    change_pct: float
    volume: Optional[int] = None
    source: str = "eastmoney"
    fetched_at: datetime = field(default_factory=datetime.now)
    citation: Optional[SourceCitation] = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "trade_date": self.trade_date.isoformat() if self.trade_date else None,
            "close": self.close,
            "prev_close": self.prev_close,
            "change_pct": self.change_pct,
            "volume": self.volume,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat(),
        }


@dataclass(frozen=True)
class USOvernightSnapshot:
    """美股隔夜大盘综合快照。"""

    trade_date: date
    sp500: Optional[USIndexSnapshot]
    nasdaq: Optional[USIndexSnapshot]
    dow: Optional[USIndexSnapshot]
    vix: Optional[USIndexSnapshot]
    summary: str = ""
    fetched_at: datetime = field(default_factory=datetime.now)
    citation: Optional[SourceCitation] = None

    def to_dict(self) -> dict:
        return {
            "trade_date": self.trade_date.isoformat() if self.trade_date else None,
            "sp500": self.sp500.to_dict() if self.sp500 else None,
            "nasdaq": self.nasdaq.to_dict() if self.nasdaq else None,
            "dow": self.dow.to_dict() if self.dow else None,
            "vix": self.vix.to_dict() if self.vix else None,
            "summary": self.summary,
            "fetched_at": self.fetched_at.isoformat(),
        }


def _fetch_eastmoney_us_indices(
    max_retries: int = 3,
) -> dict[str, USIndexSnapshot]:
    """通过东方财富 API 批量获取美股指数快照。

    Returns:
        {内部 symbol: USIndexSnapshot}
    """
    url = EASTMONEY_US_API_URL
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://quote.eastmoney.com/",
    }

    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
            data_list = (
                payload.get("data", {}) or {}
            ).get("diff", [])

            results: dict[str, USIndexSnapshot] = {}
            trade_date = date.today()
            for item in data_list:
                em_code = str(item.get("f12", ""))
                mapping = EASTMONEY_US_INDICES.get(em_code)
                if mapping is None:
                    continue
                symbol, name = mapping
                close = float(item.get("f2", 0) or 0)
                change_pct = float(item.get("f3", 0) or 0)
                prev_close = float(item.get("f18", 0) or 0)
                if close <= 0:
                    continue
                if prev_close <= 0 and change_pct != 0:
                    prev_close = close / (1 + change_pct / 100.0)

                results[symbol] = USIndexSnapshot(
                    symbol=symbol,
                    name=name,
                    trade_date=trade_date,
                    close=round(close, 4),
                    prev_close=round(prev_close, 4),
                    change_pct=round(change_pct, 4),
                    source="eastmoney",
                    citation=make_citation(
                        provider="eastmoney",
                        field=symbol,
                        data_type="us_overnight",
                        nature="fact",
                    ),
                )
            return results
        except Exception as exc:
            logger.debug("Eastmoney US indices fetch attempt %d failed: %s", attempt + 1, exc)
            if attempt < max_retries - 1:
                sleep(2 ** attempt)
    return {}


def fetch_us_overnight(
    tickers: Optional[dict[str, str]] = None,
) -> Optional[USOvernightSnapshot]:
    """获取美股隔夜大盘快照。

    Args:
        tickers: 保留参数以兼容接口，当前仅支持默认指数。

    Returns:
        USOvernightSnapshot 或 None（全部失败时）。
    """
    if tickers is not None and tickers != {
        "^GSPC": "S&P 500", "^IXIC": "Nasdaq Composite", "^DJI": "Dow Jones Industrial Average"
    }:
        logger.debug("Custom tickers not supported for Eastmoney US indices; using defaults")

    fetched = _fetch_eastmoney_us_indices()
    if not fetched:
        return None

    sp500 = fetched.get("^GSPC")
    nasdaq = fetched.get("^IXIC")
    dow = fetched.get("^DJI")

    trade_date = max(
        [s.trade_date for s in [sp500, nasdaq, dow] if s is not None],
        default=date.today(),
    )

    parts: list[str] = []
    if sp500:
        parts.append(f"S&P500 {sp500.change_pct:+.2f}%")
    if nasdaq:
        parts.append(f"Nasdaq {nasdaq.change_pct:+.2f}%")
    if dow:
        parts.append(f"Dow {dow.change_pct:+.2f}%")
    summary = " | ".join(parts)

    return USOvernightSnapshot(
        trade_date=trade_date,
        sp500=sp500,
        nasdaq=nasdaq,
        dow=dow,
        vix=None,
        summary=summary,
        citation=make_citation(
            provider="eastmoney",
            field="us_overnight",
            data_type="us_overnight",
            nature="fact",
        ),
    )
