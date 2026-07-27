# -*- coding: utf-8 -*-
"""美股隔夜大盘数据获取模块。

通过东方财富全球指数 API 免费获取 S&P 500 / Nasdaq / Dow Jones 隔夜收盘数据，
用于 A 股分析 pipeline 的宏观情绪修正。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from time import sleep
from typing import Optional

try:
    from curl_cffi import requests
except ImportError:  # pragma: no cover
    import requests  # type: ignore[no-redef]

from src.data.source_citation import SourceCitation, make_citation

logger = logging.getLogger(__name__)


# 东方财富全球指数 API 代码映射
# key: API 返回的 f12 字段; value: (内部 symbol, 显示名称, 市场)
EASTMONEY_US_INDICES: dict[str, tuple[str, str]] = {
    "SPX": ("^GSPC", "S&P 500"),
    "NDX": ("^IXIC", "Nasdaq Composite"),
    "DJIA": ("^DJI", "Dow Jones Industrial Average"),
}

# 亚洲及A股指数映射 (同一API, 不同 secids)
EASTMONEY_ASIA_INDICES: dict[str, tuple[str, str]] = {
    "N225": ("^N225", "日经225"),
    "KS11": ("^KS11", "韩国KOSPI"),
    "HSI": ("^HSI", "恒生指数"),
}

# A股大盘指数 (secids 前缀为 1)
ASHARE_INDEX_SECIDS: dict[str, str] = {
    "1.000001": "上证指数",
    "1.399001": "深证成指",
    "1.399006": "创业板指",
}

# 完整全球指数 API URL (US + 亚洲)
_ALL_GLOBAL_SECIDS = (
    "100.SPX,100.NDX,100.DJIA,"
    "100.N225,100.KS11,100.HSI"
)
_ASHARE_SECIDS = ",".join(ASHARE_INDEX_SECIDS.keys())

GLOBAL_MARKET_API_URL = (
    "https://push2.eastmoney.com/api/qt/ulist.np/get"
    f"?fltt=2&invt=2&fields=f12,f13,f14,f2,f3,f4,f18,f124"
    f"&secids={_ALL_GLOBAL_SECIDS}"
)

ASHARE_INDEX_API_URL = (
    "https://push2.eastmoney.com/api/qt/ulist.np/get"
    f"?fltt=2&invt=2&fields=f12,f13,f14,f2,f3,f4,f18,f124"
    f"&secids={_ASHARE_SECIDS}"
)

EASTMONEY_US_API_URL = GLOBAL_MARKET_API_URL  # 向后兼容


@dataclass(frozen=True)
class USIndexSnapshot:
    """单个美股指数的隔夜收盘快照。"""

    symbol: str
    name: str
    trade_date: date
    close: float
    prev_close: float
    change_pct: float
    source: str = "eastmoney"
    fetched_at: datetime = field(default_factory=datetime.now)
    citation: Optional[SourceCitation] = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "trade_date": self.trade_date.isoformat(),
            "close": self.close,
            "prev_close": self.prev_close,
            "change_pct": self.change_pct,
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
    summary: str = ""
    fetched_at: datetime = field(default_factory=datetime.now)
    citation: Optional[SourceCitation] = None

    def to_dict(self) -> dict:
        return {
            "trade_date": self.trade_date.isoformat(),
            "sp500": self.sp500.to_dict() if self.sp500 else None,
            "nasdaq": self.nasdaq.to_dict() if self.nasdaq else None,
            "dow": self.dow.to_dict() if self.dow else None,
            "summary": self.summary,
            "fetched_at": self.fetched_at.isoformat(),
        }


def _parse_trade_date(item: dict) -> date:
    """从 API 返回的 f124 Unix 时间戳推断美股交易日（UTC 日期）。"""
    ts = item.get("f124")
    if ts:
        try:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
        except Exception:
            pass
    return date.today()


def _compute_prev_close(close: float, change_pct: float, reported_prev: float) -> float:
    """计算前收盘价，优先使用 API 返回值，缺失时从涨跌幅反推。"""
    if reported_prev > 0:
        return reported_prev
    if change_pct == -100.0:
        return 0.0
    if change_pct != 0 and close > 0:
        return close / (1 + change_pct / 100.0)
    return close


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
            for item in data_list:
                em_code = str(item.get("f12", ""))
                mapping = EASTMONEY_US_INDICES.get(em_code)
                if mapping is None:
                    continue
                symbol, name = mapping
                close = float(item.get("f2", 0) or 0)
                change_pct = float(item.get("f3", 0) or 0)
                reported_prev = float(item.get("f18", 0) or 0)
                if close <= 0:
                    continue

                trade_date = _parse_trade_date(item)
                prev_close = _compute_prev_close(close, change_pct, reported_prev)

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
        summary=summary,
        citation=make_citation(
            provider="eastmoney",
            field="us_overnight",
            data_type="us_overnight",
            nature="fact",
        ),
    )


# ═══════════════════════════════════════════════════════════════════
# 全球市场综合快照 (US + 亚太 + A股)
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class GlobalMarketSnapshot:
    """全球主要市场综合快照 — 短线战术管道的宏观背景。"""

    trade_date: date
    fetched_at: datetime = field(default_factory=datetime.now)

    # US
    sp500: Optional[USIndexSnapshot] = None
    nasdaq: Optional[USIndexSnapshot] = None
    dow: Optional[USIndexSnapshot] = None
    us_summary: str = ""

    # 亚太
    nikkei: Optional[USIndexSnapshot] = None      # 日经225
    kospi: Optional[USIndexSnapshot] = None       # 韩国KOSPI
    hang_seng: Optional[USIndexSnapshot] = None   # 恒生指数
    asia_summary: str = ""

    # A股大盘
    shanghai: Optional[USIndexSnapshot] = None    # 上证指数
    shenzhen: Optional[USIndexSnapshot] = None     # 深证成指
    chi_next: Optional[USIndexSnapshot] = None     # 创业板指
    a_share_summary: str = ""

    # 全貌
    summary: str = ""                              # 一行总结: "纳指+1.2% | 日经-0.5% | 上证+0.3%"

    def to_dict(self) -> dict:
        return {
            "trade_date": self.trade_date.isoformat(),
            "fetched_at": self.fetched_at.isoformat(),
            "us": {
                "sp500": self.sp500.to_dict() if self.sp500 else None,
                "nasdaq": self.nasdaq.to_dict() if self.nasdaq else None,
                "dow": self.dow.to_dict() if self.dow else None,
            },
            "asia": {
                "nikkei": self.nikkei.to_dict() if self.nikkei else None,
                "kospi": self.kospi.to_dict() if self.kospi else None,
                "hang_seng": self.hang_seng.to_dict() if self.hang_seng else None,
            },
            "a_share": {
                "shanghai": self.shanghai.to_dict() if self.shanghai else None,
                "shenzhen": self.shenzhen.to_dict() if self.shenzhen else None,
                "chi_next": self.chi_next.to_dict() if self.chi_next else None,
            },
            "summary": self.summary,
        }


def _fetch_indices_from_url(
    url: str,
    index_map: dict[str, tuple[str, str]],
    max_retries: int = 3,
) -> dict[str, USIndexSnapshot]:
    """通用指数拉取 — 从东财API批量获取任意指数。"""
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
            data_list = (payload.get("data", {}) or {}).get("diff", [])

            results: dict[str, USIndexSnapshot] = {}
            for item in data_list:
                em_code = str(item.get("f12", ""))
                mapping = index_map.get(em_code)
                if mapping is None:
                    continue
                symbol, name = mapping
                close = float(item.get("f2", 0) or 0)
                change_pct = float(item.get("f3", 0) or 0)
                reported_prev = float(item.get("f18", 0) or 0)
                if close <= 0:
                    continue

                trade_date = _parse_trade_date(item)
                prev_close = _compute_prev_close(close, change_pct, reported_prev)

                results[symbol] = USIndexSnapshot(
                    symbol=symbol, name=name,
                    trade_date=trade_date,
                    close=round(close, 4),
                    prev_close=round(prev_close, 4),
                    change_pct=round(change_pct, 4),
                    source="eastmoney",
                )
            return results
        except Exception as exc:
            logger.debug("Index fetch attempt %d failed: %s", attempt + 1, exc)
            if attempt < max_retries - 1:
                sleep(2 ** attempt)
    return {}


def fetch_global_market(
    include_a_share: bool = True,
) -> Optional[GlobalMarketSnapshot]:
    """获取全球主要市场综合快照 (US + 亚太 + A股大盘)。

    一次API调用拉取: S&P500/Nasdaq/Dow/日经/KOSPI/恒生。
    第二次API调用拉取: 上证/深证/创业板 (如 include_a_share=True)。
    两次调用独立，可并行发起。

    Returns:
        GlobalMarketSnapshot 或 None (全部失败时)。
    """
    # 全球指数 (US + 亚太, 同一次请求)
    all_global_map: dict[str, tuple[str, str]] = {}
    all_global_map.update(EASTMONEY_US_INDICES)
    all_global_map.update(EASTMONEY_ASIA_INDICES)

    global_fetched = _fetch_indices_from_url(GLOBAL_MARKET_API_URL, all_global_map)

    snapshot = GlobalMarketSnapshot(trade_date=date.today())

    # US
    sp500 = global_fetched.get("^GSPC")
    nasdaq = global_fetched.get("^IXIC")
    dow = global_fetched.get("^DJI")
    snapshot = GlobalMarketSnapshot(
        trade_date=max(
            [s.trade_date for s in [sp500, nasdaq, dow] if s is not None],
            default=date.today(),
        ),
        sp500=sp500, nasdaq=nasdaq, dow=dow,
        nikkei=global_fetched.get("^N225"),
        kospi=global_fetched.get("^KS11"),
        hang_seng=global_fetched.get("^HSI"),
    )

    # US summary
    us_parts = []
    for s, label in [(sp500, "S&P500"), (nasdaq, "Nasdaq"), (dow, "Dow")]:
        if s:
            us_parts.append(f"{label} {s.change_pct:+.2f}%")
    snapshot = GlobalMarketSnapshot(
        trade_date=snapshot.trade_date,
        sp500=sp500, nasdaq=nasdaq, dow=dow,
        us_summary=" | ".join(us_parts),
        nikkei=snapshot.nikkei,
        kospi=snapshot.kospi,
        hang_seng=snapshot.hang_seng,
    )

    # Asia summary
    asia_parts = []
    for s, label in [
        (snapshot.nikkei, "日经"), (snapshot.kospi, "KOSPI"),
        (snapshot.hang_seng, "恒生"),
    ]:
        if s:
            asia_parts.append(f"{label} {s.change_pct:+.2f}%")
    snapshot = GlobalMarketSnapshot(
        trade_date=snapshot.trade_date,
        sp500=sp500, nasdaq=nasdaq, dow=dow,
        us_summary=snapshot.us_summary,
        nikkei=snapshot.nikkei, kospi=snapshot.kospi,
        hang_seng=snapshot.hang_seng,
        asia_summary=" | ".join(asia_parts),
    )

    # A股大盘 (独立API调用，secid前缀不同)
    if include_a_share:
        a_share_map: dict[str, tuple[str, str]] = {
            k: (k, v) for k, v in ASHARE_INDEX_SECIDS.items()
        }
        a_fetched = _fetch_indices_from_url(ASHARE_INDEX_API_URL, a_share_map)
        sh = a_fetched.get("1.000001")
        sz = a_fetched.get("1.399001")
        cy = a_fetched.get("1.399006")
        a_parts = []
        for s, label in [(sh, "上证"), (sz, "深证"), (cy, "创业板")]:
            if s:
                a_parts.append(f"{label} {s.change_pct:+.2f}%")

        snapshot = GlobalMarketSnapshot(
            trade_date=snapshot.trade_date,
            sp500=sp500, nasdaq=nasdaq, dow=dow,
            us_summary=snapshot.us_summary,
            nikkei=snapshot.nikkei, kospi=snapshot.kospi,
            hang_seng=snapshot.hang_seng,
            asia_summary=snapshot.asia_summary,
            shanghai=sh, shenzhen=sz, chi_next=cy,
            a_share_summary=" | ".join(a_parts),
        )

    # 全局一行总结
    all_parts = []
    for s, label in [
        (sp500, "S&P500"), (nasdaq, "纳指"),
        (snapshot.nikkei, "日经"), (snapshot.kospi, "韩股"),
        (snapshot.shanghai, "上证"),
    ]:
        if s and s.change_pct != 0:
            all_parts.append(f"{label}{s.change_pct:+.1f}%")
    snapshot = GlobalMarketSnapshot(
        trade_date=snapshot.trade_date,
        sp500=snapshot.sp500, nasdaq=snapshot.nasdaq, dow=snapshot.dow,
        us_summary=snapshot.us_summary,
        nikkei=snapshot.nikkei, kospi=snapshot.kospi,
        hang_seng=snapshot.hang_seng,
        asia_summary=snapshot.asia_summary,
        shanghai=snapshot.shanghai, shenzhen=snapshot.shenzhen,
        chi_next=snapshot.chi_next,
        a_share_summary=snapshot.a_share_summary,
        summary=" | ".join(all_parts),
    )

    # 判断是否完全不可用
    if not any([sp500, nasdaq, dow,
                snapshot.nikkei, snapshot.kospi, snapshot.hang_seng,
                snapshot.shanghai]):
        return None

    return snapshot
