"""Dragon & Tiger (龙虎榜) + Limit-up pool analysis — 东财 datacenter primary source.

V2: Replaced AKShare with 东财 datacenter direct HTTP API (a-stock-data pattern).
Added limit-up / break-board / limit-down pool analysis for hot-money dominance detection.
"""

from __future__ import annotations

import logging
import time
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── 东财防封 helpers (from a-stock-data) ──────────────────────────
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_EM_SESSION = None
_em_last_call = 0.0
EM_MIN_INTERVAL = 1.2

def _get_em_session():
    global _EM_SESSION
    if _EM_SESSION is None:
        import requests
        _EM_SESSION = requests.Session()
        _EM_SESSION.trust_env = False  # 禁止读取系统代理，避免代理工具干扰东财 API 连接
        _EM_SESSION.headers.update({"User-Agent": UA})
        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            _EM_SESSION.mount("https://", HTTPAdapter(max_retries=Retry(
                total=2, connect=2, backoff_factor=0.5,
                status_forcelist=[429, 500, 502, 503], allowed_methods=["GET"])))
        except Exception:
            pass
    return _EM_SESSION

def _em_get(url: str, params: dict = None, headers: dict = None, timeout: int = 15):
    global _em_last_call
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call)
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return _get_em_session().get(url, params=params, headers=headers or {}, timeout=timeout)
    finally:
        _em_last_call = time.time()

DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

def _dc_query(report_name: str, filter_str: str = "", page_size: int = 50,
              sort_columns: str = "", sort_types: str = "-1") -> list[dict]:
    r = _em_get(DATACENTER_URL, params={
        "reportName": report_name, "columns": "ALL",
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }, timeout=15)
    d = r.json()
    return (d.get("result") or {}).get("data") or []


# ── Data models ─────────────────────────────────────────────────────

@dataclass
class SeatInfo:
    seat_name: str
    reputation_score: int
    known_aliases: list[str] = field(default_factory=list)
    typical_sectors: list[str] = field(default_factory=list)
    avg_position_size: float = 0.0
    holding_period: str = "短线"


@dataclass
class SeatActivity:
    seat_name: str
    stock_symbol: str
    stock_name: str = ""
    buy_amount: float = 0.0
    sell_amount: float = 0.0
    net_amount: float = 0.0
    seat_info: Optional[SeatInfo] = None
    following_signal: str = "neutral"
    identified: bool = False
    date: str = ""
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class LimitUpSnapshot:
    """打板情绪快照。"""
    date: str = ""
    zt_count: int = 0       # 涨停家数
    zb_count: int = 0       # 炸板家数
    dt_count: int = 0       # 跌停家数
    break_rate: float = 0.0  # 炸板率%
    max_height: int = 0      # 最高连板
    ladder: dict = field(default_factory=dict)  # {板数: 家数}


# ── Known hot-money seat database (unchanged, domain knowledge) ─────

KNOWN_SEATS: list[SeatInfo] = [
    SeatInfo("中信证券上海分公司", 85, ["中信上海"], ["科技", "半导体"], 5000, "短线"),
    SeatInfo("华泰证券深圳益田路", 90, ["华泰益田路", "益田路"], ["次新股", "题材"], 8000, "隔日"),
    SeatInfo("招商证券深圳深南东路", 80, ["招商深南东"], ["科技", "军工"], 4000, "短线"),
    SeatInfo("国泰君安上海分公司", 75, ["国君上海"], ["金融", "消费"], 6000, "短线"),
    SeatInfo("光大证券深圳金田路", 82, ["光大金田路"], ["科技", "新能源"], 4500, "短线"),
    SeatInfo("中国银河证券绍兴", 88, ["银河绍兴", "绍兴"], ["题材", "妖股"], 10000, "隔日"),
    SeatInfo("东方证券上海浦东新区银城中路", 78, ["银城中路"], ["消费", "医药"], 3500, "短线"),
    SeatInfo("华鑫证券上海分公司", 72, ["华鑫上海"], ["次新", "题材"], 3000, "隔日"),
    SeatInfo("中信建投证券北京东直门", 70, ["中信建投东直门"], ["科技"], 3500, "短线"),
    SeatInfo("国盛证券宁波桑田路", 86, ["宁波桑田路", "桑田路"], ["妖股", "题材"], 9000, "隔日"),
    SeatInfo("财通证券杭州上塘路", 83, ["杭州上塘路", "上塘路"], ["科技", "新能源"], 7000, "短线"),
    SeatInfo("申万宏源上海闵行区东川路", 76, ["东川路"], ["消费", "医药"], 4000, "中线"),
    SeatInfo("中信证券上海淮海中路", 74, ["淮海中路"], ["金融", "周期"], 5000, "短线"),
    SeatInfo("华泰证券上海武定路", 79, ["武定路"], ["科技", "军工"], 4500, "短线"),
    SeatInfo("国金证券上海互联网证券分公司", 68, ["国金互联网"], ["科技"], 2500, "短线"),
    SeatInfo("东方财富证券拉萨团结路", 60, ["拉萨团结路", "拉萨"], ["题材", "次新"], 1500, "短线"),
    SeatInfo("东方财富证券拉萨东环路", 60, ["拉萨东环路", "东环路"], ["题材", "次新"], 1500, "短线"),
    SeatInfo("平安证券深圳深南东路", 65, ["平安深南东"], ["金融"], 3000, "中线"),
    SeatInfo("国信证券深圳泰然九路", 67, ["泰然九路"], ["科技", "消费"], 3500, "短线"),
    SeatInfo("广发证券上海东方路", 71, ["广发东方路"], ["金融", "地产"], 4000, "中线"),
    SeatInfo("中泰证券上海花园石桥路", 73, ["花园石桥路"], ["消费", "医药"], 3800, "短线"),
    SeatInfo("兴业证券陕西分公司", 69, ["兴业陕西"], ["军工", "新能源"], 3200, "短线"),
    SeatInfo("长江证券上海东明路", 66, ["东明路"], ["科技"], 2800, "短线"),
    SeatInfo("中信证券深圳深南大道", 77, ["中信深南大道"], ["科技", "消费"], 4200, "短线"),
    SeatInfo("浙商证券杭州杭大路", 63, ["杭大路"], ["科技"], 2500, "短线"),
    SeatInfo("国泰君安南京太平南路", 81, ["南京太平南路"], ["题材", "科技"], 6500, "隔日"),
    SeatInfo("华泰证券南京中华路", 70, ["南京中华路"], ["次新", "题材"], 3000, "短线"),
    SeatInfo("中信证券杭州延安路", 75, ["杭州延安路", "延安路"], ["科技", "新能源"], 5000, "短线"),
    SeatInfo("兴业证券厦门湖滨南路", 67, ["厦门湖滨南路"], ["消费", "医药"], 2800, "短线"),
    SeatInfo("海通证券上海建国西路", 64, ["建国西路"], ["周期", "金融"], 3500, "中线"),
]


# ── Main tracker class ──────────────────────────────────────────────

class SeatTracker:
    """Track hot-money seats from 东财 datacenter dragon & tiger data + limit-up pools."""

    def __init__(self):
        self._seats: dict[str, SeatInfo] = {}
        self._build_index()

    def _build_index(self):
        for seat in KNOWN_SEATS:
            self._seats[seat.seat_name] = seat
            for alias in seat.known_aliases:
                if alias not in self._seats:
                    self._seats[alias] = seat

    # ------------------------------------------------------------------
    # Public API — Dragon & Tiger
    # ------------------------------------------------------------------

    def analyze_daily(self, symbol: str = "", trade_date: str = "") -> list[SeatActivity]:
        """Analyze today's dragon & tiger list from 东财 datacenter."""
        if not trade_date:
            trade_date = datetime.now().strftime("%Y-%m-%d")

        activities: list[SeatActivity] = []

        # Full market dragon & tiger
        stocks_data = self._fetch_daily_dt_market(trade_date)
        if symbol:
            stocks_data = [s for s in stocks_data if s.get("SECURITY_CODE") == symbol]

        if not stocks_data:
            # Fallback: try yesterday
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            stocks_data = self._fetch_daily_dt_market(yesterday)
            if symbol:
                stocks_data = [s for s in stocks_data if s.get("SECURITY_CODE") == symbol]

        for stock in stocks_data:
            code = stock.get("SECURITY_CODE", "")
            name = stock.get("SECURITY_NAME_ABBR", "")
            date = str(stock.get("TRADE_DATE", ""))[:10]

            # Fetch buy/sell seat details for this stock
            buy_seats = self._fetch_seat_details(code, date, "BUY")
            sell_seats = self._fetch_seat_details(code, date, "SELL")

            # Process buy seats
            seat_activities: dict[str, SeatActivity] = {}
            for s in buy_seats[:5]:
                seat_name = s.get("OPERATEDEPT_NAME", "")
                if not seat_name:
                    continue
                activity = self._classify_seat(seat_name, code, name, date)
                activity.buy_amount = (s.get("BUY") or 0) / 10000  # 元→万元
                activity.sell_amount = (s.get("SELL") or 0) / 10000
                activity.net_amount = (s.get("NET") or 0) / 10000
                if activity.identified:
                    seat_activities[seat_name] = activity

            # Merge sell seats
            for s in sell_seats[:5]:
                seat_name = s.get("OPERATEDEPT_NAME", "")
                if not seat_name:
                    continue
                if seat_name in seat_activities:
                    seat_activities[seat_name].sell_amount = (s.get("SELL") or 0) / 10000
                    seat_activities[seat_name].net_amount = (
                        seat_activities[seat_name].buy_amount - seat_activities[seat_name].sell_amount
                    )
                else:
                    activity = self._classify_seat(seat_name, code, name, date)
                    activity.sell_amount = (s.get("SELL") or 0) / 10000
                    activity.net_amount = -activity.sell_amount
                    if activity.identified:
                        seat_activities[seat_name] = activity

            activities.extend(seat_activities.values())

        return activities

    def get_market_seat_summary(self) -> dict:
        activities = self.analyze_daily()
        identified = [a for a in activities if a.identified]
        buy_total = sum(a.buy_amount for a in identified)
        seat_counts: dict[str, int] = {}
        for a in identified:
            seat_counts[a.seat_name] = seat_counts.get(a.seat_name, 0) + 1
        top_seats = sorted(seat_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "active_count": len(set(a.seat_name for a in identified)),
            "total_activities": len(identified),
            "total_buy_amount": buy_total,
            "top_seats": top_seats,
            "hot_money_active": len(identified) >= 5,
        }

    # ------------------------------------------------------------------
    # Public API — Limit-up pools (打板层)
    # ------------------------------------------------------------------

    def get_limit_up_snapshot(self, date: str = "") -> LimitUpSnapshot:
        """Fetch limit-up sentiment snapshot from 东财 push2ex."""
        if not date:
            date = datetime.now().strftime("%Y%m%d")

        sn = LimitUpSnapshot(date=date)

        try:
            zt_pool = self._fetch_zt_pool("getTopicZTPool", "fbt:asc", date)
            zb_pool = self._fetch_zt_pool("getTopicZBPool", "fbt:asc", date)
            dt_pool = self._fetch_zt_pool("getTopicDTPool", "fund:asc", date)

            sn.zt_count = len(zt_pool)
            sn.zb_count = len(zb_pool)
            sn.dt_count = len(dt_pool)

            total_attempts = sn.zt_count + sn.zb_count
            if total_attempts > 0:
                sn.break_rate = round(sn.zb_count / total_attempts * 100, 1)

            # Ladder
            ladder: dict[int, int] = {}
            for s in zt_pool:
                days = s.get("lbc", 0) or 0
                ladder[days] = ladder.get(days, 0) + 1
            sn.ladder = dict(sorted(ladder.items()))
            sn.max_height = max(ladder.keys()) if ladder else 0
        except Exception as e:
            logger.warning("Limit-up pool fetch failed: %s", e)

        return sn

    def is_hot_money_active(self, date: str = "") -> bool:
        """Quick check: is hot money dominating today?"""
        sn = self.get_limit_up_snapshot(date)
        # Hot-money signal: >50 limit-ups AND break rate <30% (strong seals)
        return sn.zt_count >= 50 and sn.break_rate < 30

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify_seat(self, seat_name: str, symbol: str = "", name: str = "",
                       date: str = "") -> SeatActivity:
        activity = SeatActivity(seat_name=seat_name, stock_symbol=symbol,
                                stock_name=name, date=date)
        seat_info = self._seats.get(seat_name)
        if seat_info is None:
            for known_name, info in self._seats.items():
                if known_name in seat_name or seat_name in known_name:
                    seat_info = info
                    break

        if seat_info is not None:
            activity.identified = True
            activity.seat_info = seat_info
            if seat_info.reputation_score >= 85:
                activity.following_signal = "strong_buy"
            elif seat_info.reputation_score >= 70:
                activity.following_signal = "buy"
        return activity

    # ------------------------------------------------------------------
    # Data fetching — 东财 datacenter
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_daily_dt_market(trade_date: str) -> list[dict]:
        """全市场龙虎榜 — 东财 datacenter."""
        return _dc_query(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=f"(TRADE_DATE>='{trade_date}')(TRADE_DATE<='{trade_date}')",
            page_size=500,
            sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
        )

    @staticmethod
    def _fetch_seat_details(code: str, trade_date: str, side: str) -> list[dict]:
        """买入/卖出席位明细."""
        report = f"RPT_BILLBOARD_DAILYDETAILS{side}"
        return _dc_query(
            report,
            filter_str=f"(TRADE_DATE='{trade_date}')(SECURITY_CODE=\"{code}\")",
            page_size=10,
            sort_columns=side, sort_types="-1",
        )

    @staticmethod
    def _fetch_zt_pool(endpoint: str, sort: str, date: str) -> list[dict]:
        """涨停板池 — 东财 push2ex."""
        try:
            url = f"https://push2ex.eastmoney.com/{endpoint}"
            params = {
                "ut": "7eea3edcaed734bea9cbfc24409ed989",
                "dpt": "wz.ztzt", "Pageindex": 0,
                "pagesize": 10000, "sort": sort, "date": date,
            }
            r = _em_get(url, params=params,
                        headers={"Referer": "https://quote.eastmoney.com/"}, timeout=10)
            return (r.json().get("data") or {}).get("pool") or []
        except Exception as e:
            logger.debug("ZT pool fetch failed: %s", e)
            return []

    @staticmethod
    def list_known_seats() -> list[SeatInfo]:
        return list(KNOWN_SEATS)

    @staticmethod
    def _safe_float(val) -> float:
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0
