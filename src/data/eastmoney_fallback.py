# -*- coding: utf-8 -*-
"""东财 / 巨潮 HTTP 降级源。

当主源 (妙想 mx-search / mx-data / mx-xuangu) 不可用时，自动降级到以下免费源：
  - 东财个股新闻 (search-api-web JSONP)
  - 东财全球 7×24 快讯 (np-weblist)
  - 巨潮 cninfo 公告 (hisAnnouncement/query)
  - 东财研报 (reportapi)
  - 东财 datacenter (高管交易 / 分红)
  - 东财 push2 (行业排名 / 行业成分股)

所有函数无状态、内置 _em_get() 限流 (1.0s min interval + random jitter)。
返回原始 dict/list-of-dict，DTO 转换由 DataAggregator 负责。
"""

from __future__ import annotations

import json
import logging
import random
import socket
import ssl
import time
import uuid
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# ── 防封常量 ───────────────────────────────────────────────────────
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_MIN_INTERVAL = 1.0  # 最小请求间隔 (秒)

_em_session: Optional[requests.Session] = None
_em_last_call: float = 0.0


def _get_em_session() -> requests.Session:
    global _em_session
    if _em_session is None:
        _em_session = requests.Session()
        _em_session.headers.update({"User-Agent": UA})
        try:
            _em_session.mount(
                "https://",
                HTTPAdapter(
                    max_retries=Retry(
                        total=3,
                        connect=3,
                        backoff_factor=0.6,
                        status_forcelist=[429, 500, 502, 503, 504],
                        allowed_methods=["GET"],
                    )
                ),
            )
            _em_session.mount(
                "http://",
                HTTPAdapter(
                    max_retries=Retry(
                        total=2,
                        connect=2,
                        backoff_factor=0.5,
                        status_forcelist=[500, 502, 503],
                        allowed_methods=["GET"],
                    )
                ),
            )
        except Exception:
            pass
    return _em_session


def _em_get(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = 15,
    **kwargs,
) -> requests.Response:
    """东财统一请求入口：自动节流 + 复用 session + 默认 UA。"""
    global _em_last_call
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call)
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return _get_em_session().get(
            url, params=params, headers=headers or {}, timeout=timeout, **kwargs
        )
    finally:
        _em_last_call = time.time()


# ── URL 常量 ────────────────────────────────────────────────────────
SEARCH_API = "https://search-api-web.eastmoney.com/search/jsonp"
NEWS_LIST_URL = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
REPORT_API = "https://reportapi.eastmoney.com/report/list"
PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
PUSH2_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
PUSH2_URL = "https://push2.eastmoney.com/api/qt/stock/get"
CNINFO_ANNOUNCE_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_ORGID_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"

# ── 巨潮 orgId 缓存（deprecated，委托给 CninfoProvider） ────────────
_cninfo_orgid_map: dict[str, str] = {}
_cninfo_orgid_loaded: bool = False


def _load_cninfo_orgid_map():
    """[deprecated] 委托给 CninfoProvider._load_orgid_map()。"""
    global _cninfo_orgid_loaded, _cninfo_orgid_map
    try:
        from .cninfo import _get_default_provider
        p = _get_default_provider()
        p._load_orgid_map()
        _cninfo_orgid_map = p._orgid_map
        _cninfo_orgid_loaded = p._orgid_loaded
    except Exception:
        if not _cninfo_orgid_loaded:
            _cninfo_orgid_loaded = True


def _cninfo_orgid(code: str) -> str:
    """[deprecated] 委托给 CninfoProvider._get_orgid()。"""
    try:
        from .cninfo import _get_default_provider
        return _get_default_provider()._get_orgid(code)
    except Exception:
        if code.startswith("6"):
            return f"gssh0{code}"
        elif code.startswith("8") or code.startswith("4"):
            return f"gsbj0{code}"
        return f"gssz0{code}"


def _cninfo_ts_to_date(ts) -> str:
    """[deprecated] 委托给 CninfoProvider._ts_to_date()。"""
    try:
        from .cninfo import _get_default_provider
        return _get_default_provider()._ts_to_date(ts)
    except Exception:
        from datetime import datetime
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        return str(ts)[:10] if ts else ""


# ══════════════════════════════════════════════════════════════════════
# 新闻降级
# ══════════════════════════════════════════════════════════════════════


def fetch_em_stock_news(code_or_query: str, max_results: int = 20) -> list[dict]:
    """东财个股新闻搜索 (search-api-web JSONP, 零鉴权)。

    Args:
        code_or_query: 股票代码或搜索关键词
        max_results: 最大返回条数

    Returns:
        [{title, content, time, source, url}, ...]
    """
    cb = "jQuery_news"
    inner = json.dumps(
        {
            "uid": "",
            "keyword": code_or_query,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": max_results,
                    "preTag": "",
                    "postTag": "",
                }
            },
        },
        separators=(",", ":"),
    )
    params = {"cb": cb, "param": inner}
    headers = {"Referer": "https://so.eastmoney.com/"}

    try:
        r = _em_get(SEARCH_API, params=params, headers=headers, timeout=15)
        text = r.text
        json_str = text[text.index("(") + 1 : text.rindex(")")]
        d = json.loads(json_str)
        articles = d.get("result", {}).get("cmsArticleWebOld", []) or []
        rows = []
        for a in articles[:max_results]:
            rows.append(
                {
                    "title": _strip_html(a.get("title", "")),
                    "content": _strip_html(a.get("content", ""))[:500],
                    "time": a.get("date", ""),
                    "source": a.get("mediaName", ""),
                    "url": a.get("url", ""),
                }
            )
        return rows
    except Exception as e:
        logger.debug("东财个股新闻获取失败: %s", e)
        return []


def fetch_em_global_news(page_size: int = 50) -> list[dict]:
    """东财全球 7×24 财经快讯 (np-weblist, 零鉴权)。

    Returns:
        [{title, summary, time}, ...]
    """
    params = {
        "client": "web",
        "biz": "web_724",
        "fastColumn": "102",
        "sortEnd": "",
        "pageSize": str(page_size),
        "req_trace": str(uuid.uuid4()),
    }
    headers = {"Referer": "https://kuaixun.eastmoney.com/"}

    try:
        r = _em_get(NEWS_LIST_URL, params=params, headers=headers, timeout=10)
        d = r.json()
        rows = []
        for item in d.get("data", {}).get("fastNewsList", []):
            rows.append(
                {
                    "title": item.get("title", ""),
                    "summary": item.get("summary", "")[:500],
                    "time": item.get("showTime", ""),
                    "source": "东财全球",
                    "url": "",
                }
            )
        return rows
    except Exception as e:
        logger.debug("东财全球资讯获取失败: %s", e)
        return []


# ══════════════════════════════════════════════════════════════════════
# 公告降级
# ══════════════════════════════════════════════════════════════════════


def fetch_cninfo_announcements(symbol: str, page_size: int = 30) -> list[dict]:
    """巨潮 cninfo 公告检索 (POST, 零鉴权)。

    委托给 CninfoProvider.search_announcements()。

    Args:
        symbol: 6 位股票代码
        page_size: 返回条数

    Returns:
        [{title, type, date, url}, ...]
    """
    try:
        from .cninfo import _get_default_provider
        return _get_default_provider().search_announcements(symbol, page_size=page_size)
    except Exception as e:
        logger.debug("巨潮公告获取失败 (%s): %s", symbol, e)
        return []


# ══════════════════════════════════════════════════════════════════════
# 研报降级
# ══════════════════════════════════════════════════════════════════════


def fetch_em_research_reports(
    symbol: str, max_pages: int = 3
) -> list[dict]:
    """东财研报列表 (reportapi, 零鉴权)。

    Args:
        symbol: 6 位股票代码
        max_pages: 最多翻页数

    Returns:
        [{title, org, date, rating, eps_cur, eps_next, eps_next2, info_code}, ...]
    """
    all_records = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*",
            "pageSize": "50",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": "2024-01-01",
            "endTime": "2030-01-01",
            "pageNo": str(page),
            "fields": "",
            "qType": "0",
            "orgCode": "",
            "code": symbol,
            "rcode": "",
        }
        headers = {"Referer": "https://data.eastmoney.com/"}

        try:
            r = _em_get(REPORT_API, params=params, headers=headers, timeout=30)
            d = r.json()
            rows = d.get("data") or []
            if not rows:
                break
            for row in rows:
                all_records.append(
                    {
                        "title": row.get("title", ""),
                        "org": row.get("orgSName", ""),
                        "date": (row.get("publishDate") or "")[:10],
                        "rating": row.get("emRatingName", ""),
                        "eps_cur": row.get("predictThisYearEps"),
                        "eps_next": row.get("predictNextYearEps"),
                        "eps_next2": row.get("predictNextTwoYearEps"),
                        "info_code": row.get("infoCode", ""),
                    }
                )
            if page >= (d.get("TotalPage", 1) or 1):
                break
        except Exception as e:
            logger.debug("东财研报获取失败 (%s page %d): %s", symbol, page, e)
            break
    return all_records


# ══════════════════════════════════════════════════════════════════════
# 高管交易降级
# ══════════════════════════════════════════════════════════════════════


def fetch_em_executive_trades(
    symbol: str, page_size: int = 20
) -> list[dict]:
    """东财 datacenter 高管增减持 (RPT_EXECUTIVE_TRADE, 零鉴权)。

    Returns:
        [{name, position, trade_type, date, volume, price, total_value, change_pct}, ...]
    """
    # reportName 不准确时尝试两个常见路径
    for report in ("RPT_EXECUTIVE_TRADE", "RPTA_EXECUTIVE_HOLDING"):
        try:
            data = _dc_query(
                report,
                filter_str=f'(SECURITY_CODE="{symbol}")',
                page_size=page_size,
                sort_columns="CHANGE_DATE",
                sort_types="-1",
            )
            if data:
                rows = []
                for row in data:
                    rows.append(
                        {
                            "name": row.get("CHANGE_NAME", "") or row.get("EXECUTIVE_NAME", ""),
                            "position": row.get("POSITION", "") or row.get("EXECUTIVE_DUTY", ""),
                            "trade_type": _normalize_trade_type(row),
                            "date": _safe_date(row, ["CHANGE_DATE", "TRADE_DATE"]),
                            "volume": _safe_int(row, ["CHANGE_VOLUME", "TRADE_VOLUME"]),
                            "price": _safe_float(row, ["TRADE_PRICE", "AVERAGE_PRICE"]),
                            "total_value": _safe_float(row, ["TRADE_AMT", "HOLD_VALUE"]),
                            "change_pct": _safe_float(row, ["CHANGE_RATIO", "HOLD_RATIO"]),
                        }
                    )
                return rows
        except Exception as e:
            logger.debug("东财高管交易 (%s) 失败: %s", report, e)
            continue
    return []


# ══════════════════════════════════════════════════════════════════════
# 行业数据降级
# ══════════════════════════════════════════════════════════════════════


def fetch_em_industry_list() -> list[dict]:
    """东财 push2 行业板块排名 (m:90+t:2, 零鉴权)。

    Returns:
        [{name, code, change_pct, up_count, down_count, leader, leader_change}, ...]
    """
    params = {
        "pn": "1",
        "pz": "150",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}

    try:
        r = _em_get(PUSH2_CLIST_URL, params=params, headers=headers, timeout=15)
        d = r.json()
        items = d.get("data", {}).get("diff", [])
        if not items:
            return []
        rows = []
        for i, item in enumerate(items):
            rows.append(
                {
                    "rank": i + 1,
                    "name": item.get("f14", ""),
                    "code": item.get("f12", ""),
                    "change_pct": item.get("f3", 0),
                    "up_count": item.get("f104", 0),
                    "down_count": item.get("f105", 0),
                    "leader": item.get("f140", ""),
                    "leader_change": item.get("f136", 0),
                }
            )
        return rows
    except Exception as e:
        logger.debug("东财行业列表获取失败: %s", e)
        return []


def fetch_em_industry_stocks(industry_name: str) -> list[dict]:
    """东财 push2 行业成分股 (m:90+t:2 + 行业过滤, 零鉴权)。

    先拉全行业列表 → 找到目标行业 → 拉该行业成分股。

    Returns:
        [{code, name, price, change_pct, pe, pb, mcap}, ...]
    """
    # 1. 找到目标行业
    industries = fetch_em_industry_list()
    matched = None
    for ind in industries:
        if industry_name in ind.get("name", ""):
            matched = ind
            break
    if not matched:
        logger.debug("未找到行业: %s", industry_name)
        return []

    industry_code = matched.get("code", "")
    if not industry_code:
        return []

    # 2. 拉行业成分股
    params = {
        "pn": "1",
        "pz": "200",
        "po": "0",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fs": f"b:{industry_code}+f:!200",
        "fields": "f2,f3,f4,f9,f10,f12,f14,f20,f21,f115",
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}

    try:
        r = _em_get(PUSH2_CLIST_URL, params=params, headers=headers, timeout=15)
        d = r.json()
        items = d.get("data", {}).get("diff", [])
        rows = []
        for item in items:
            rows.append(
                {
                    "code": item.get("f12", ""),
                    "name": item.get("f14", ""),
                    "price": item.get("f2"),
                    "change_pct": item.get("f3"),
                    "pe": item.get("f9"),
                    "pb": item.get("f115") or item.get("f23"),
                    "mcap": item.get("f20"),  # 总市值(元)
                }
            )
        return rows
    except Exception as e:
        logger.debug("东财行业成分股获取失败 (%s): %s", industry_name, e)
        return []


def fetch_em_industry_pe_pb() -> tuple[Optional[float], Optional[float]]:
    """东财 push2 行业板块 PE/PB 中位数 (零鉴权)。

    通过 push2 clist 获取全行业，取 PE(列索引9) / PB(列索引115) 中位数。

    Returns:
        (pe_median, pb_median) — None if unavailable
    """
    params = {
        "pn": "1",
        "pz": "150",
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f9,f12,f14,f20,f115",  # f9=PE, f115=PB
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}

    try:
        r = _em_get(PUSH2_CLIST_URL, params=params, headers=headers, timeout=15)
        d = r.json()
        items = d.get("data", {}).get("diff", [])
        if not items:
            return None, None

        pe_vals, pb_vals = [], []
        for item in items:
            pe = _safe_numeric(item.get("f9"))
            pb = _safe_numeric(item.get("f115"))
            if pe is not None and pe > 0:
                pe_vals.append(pe)
            if pb is not None and pb > 0:
                pb_vals.append(pb)

        if not pe_vals and not pb_vals:
            return None, None

        pe_median = round(float(sorted(pe_vals)[len(pe_vals) // 2]), 2) if pe_vals else None
        pb_median = round(float(sorted(pb_vals)[len(pb_vals) // 2]), 2) if pb_vals else None
        return pe_median, pb_median
    except Exception as e:
        logger.debug("东财行业PE/PB获取失败: %s", e)
        return None, None


# ══════════════════════════════════════════════════════════════════════
# 分红降级
# ══════════════════════════════════════════════════════════════════════


def fetch_em_dividend(symbol: str) -> list[dict]:
    """东财 datacenter 分红送转 (RPT_SHAREBONUS_DET, 零鉴权)。

    Returns:
        [{date, bonus_rmb, transfer_ratio, bonus_ratio, plan}, ...]
    """
    try:
        data = _dc_query(
            "RPT_SHAREBONUS_DET",
            filter_str=f'(SECURITY_CODE="{symbol}")',
            page_size=10,
            sort_columns="EX_DIVIDEND_DATE",
            sort_types="-1",
        )
        rows = []
        for row in data:
            rows.append(
                {
                    "date": str(row.get("EX_DIVIDEND_DATE", ""))[:10],
                    "bonus_rmb": row.get("PRETAX_BONUS_RMB", 0),  # 每股派息(税前)
                    "transfer_ratio": row.get("TRANSFER_RATIO", 0),  # 每10股转增
                    "bonus_ratio": row.get("BONUS_RATIO", 0),  # 每10股送股
                    "plan": row.get("ASSIGN_PROGRESS", ""),
                }
            )
        return rows
    except Exception as e:
        logger.debug("东财分红数据获取失败 (%s): %s", symbol, e)
        return []


# ══════════════════════════════════════════════════════════════════════
# 内部 helpers
# ══════════════════════════════════════════════════════════════════════

import re as _re

_HTML_RE = _re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_RE.sub("", text)


def _dc_query(
    report_name: str,
    filter_str: str = "",
    page_size: int = 50,
    sort_columns: str = "",
    sort_types: str = "-1",
) -> list[dict]:
    """东财 datacenter 统一查询 helper。"""
    params = {
        "reportName": report_name,
        "columns": "ALL",
        "filter": filter_str,
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": sort_columns,
        "sortTypes": sort_types,
        "source": "WEB",
        "client": "WEB",
    }
    try:
        r = _em_get(DATACENTER_URL, params=params, timeout=15)
        d = r.json()
        if d.get("result") and d["result"].get("data"):
            return d["result"]["data"]
        return []
    except Exception:
        return []


def _normalize_trade_type(row: dict) -> str:
    """标准化高管交易方向: buy / sell。"""
    direction = row.get("CHANGE_TYPE", "") or row.get("TRADE_TYPE", "") or ""
    if "减持" in str(direction) or "卖" in str(direction) or str(direction).lower() == "sell":
        return "sell"
    if "增持" in str(direction) or "买" in str(direction) or str(direction).lower() == "buy":
        return "buy"
    # 通过数量判断
    vol = _safe_int(row, ["CHANGE_VOLUME", "TRADE_VOLUME"])
    if vol is not None and vol < 0:
        return "sell"
    return "buy"


def _safe_date(row: dict, candidates: list[str]) -> str:
    for key in candidates:
        v = row.get(key)
        if v is not None and str(v):
            return str(v)[:10]
    return ""


def _safe_int(row: dict, candidates: list[str]) -> Optional[int]:
    for key in candidates:
        v = row.get(key)
        if v is not None:
            try:
                return int(v)
            except (ValueError, TypeError):
                continue
    return None


def _safe_float(row: dict, candidates: list[str]) -> Optional[float]:
    for key in candidates:
        v = row.get(key)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                continue
    return None


def _safe_numeric(v) -> Optional[float]:
    """安全转换为 float，处理 str/None/nan。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if str(v) != "nan" else None
    try:
        f = float(v)
        return f if str(f) != "nan" else None
    except (ValueError, TypeError):
        return None
