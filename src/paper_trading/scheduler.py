# -*- coding: utf-8 -*-
"""交易日历 — A 股交易日判断 + 定时调度工具。

提供:
  - is_trading_day(): 判断当日是否为交易日
  - next_trading_day(): 获取下一个交易日
  - trading_days_in_range(): 获取日期范围内的交易日列表
  - 简单规则: 周一至周五，排除中国法定节假日
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# 中国法定节假日 (2026年，已知)
# 完整列表需要每年更新或接入外部 API
_CN_HOLIDAYS_2026: set[str] = {
    # 元旦
    "2026-01-01", "2026-01-02", "2026-01-03",
    # 春节 (2026-02-17 除夕)
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
    "2026-02-20", "2026-02-21", "2026-02-22",
    # 清明节
    "2026-04-05", "2026-04-06",
    # 劳动节
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    # 端午节
    "2026-06-19", "2026-06-20", "2026-06-21",
    # 中秋节
    "2026-09-25", "2026-09-26", "2026-09-27",
    # 国庆节
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
    "2026-10-05", "2026-10-06", "2026-10-07",
}

# 调休工作日 (周末但上班)
_CN_WORKDAYS_2026: set[str] = {
    # 春节调休
    "2026-02-14",  # 周六上班
    "2026-02-15",  # 周日上班 (2026年春节前)
    # 清明节调休
    "2026-04-04",  # 周六上班
    # 劳动节调休
    "2026-04-26",  # 周日上班
    # 端午节调休
    "2026-06-13",  # 周六上班
    # 中秋节/国庆节调休
    "2026-09-19",  # 周六上班
    "2026-09-20",  # 周日上班
    "2026-10-10",  # 周六上班
}

# 已知的半天交易日 (下午休市)
_HALF_DAYS_2026: set[str] = {
    # 通常春节前最后一个交易日为半天
    "2026-02-13",  # 待确认
    "2026-12-31",  # 年末半天
}


def _all_holidays() -> set[str]:
    """合并所有已知节假日。"""
    return _CN_HOLIDAYS_2026


def _all_workdays() -> set[str]:
    """合并所有调休工作日。"""
    return _CN_WORKDAYS_2026


# ══════════════════════════════════════════════════════════════════════
# 公共 API
# ══════════════════════════════════════════════════════════════════════


def is_trading_day(d: Optional[date] = None) -> bool:
    """判断指定日期是否为 A 股交易日。

    规则:
      1. 周一至周五
      2. 非中国法定节假日
      3. 调休工作日视为交易日

    Args:
        d: 日期，None 表示今天
    """
    if d is None:
        d = date.today()

    date_str = d.strftime("%Y-%m-%d")

    # 调休工作日: 虽然周末但是交易日
    if date_str in _all_workdays():
        return True

    # 周末
    if d.weekday() >= 5:  # 5=Sat, 6=Sun
        return False

    # 节假日
    if date_str in _all_holidays():
        return False

    return True


def is_half_trading_day(d: Optional[date] = None) -> bool:
    """判断是否为半天交易日。"""
    if d is None:
        d = date.today()
    date_str = d.strftime("%Y-%m-%d")
    return date_str in _HALF_DAYS_2026


def next_trading_day(d: Optional[date] = None) -> date:
    """获取下一个交易日 (不含当日)。"""
    if d is None:
        d = date.today()
    cursor = d + timedelta(days=1)
    max_days = 30  # 安全上限
    for _ in range(max_days):
        if is_trading_day(cursor):
            return cursor
        cursor += timedelta(days=1)
    return cursor


def prev_trading_day(d: Optional[date] = None) -> date:
    """获取上一个交易日 (不含当日)。"""
    if d is None:
        d = date.today()
    cursor = d - timedelta(days=1)
    for _ in range(30):
        if is_trading_day(cursor):
            return cursor
        cursor -= timedelta(days=1)
    return cursor


def trading_days_in_range(start: date, end: date) -> list[date]:
    """获取日期范围内的所有交易日。"""
    result: list[date] = []
    cursor = start
    while cursor <= end:
        if is_trading_day(cursor):
            result.append(cursor)
        cursor += timedelta(days=1)
    return result


def trading_days_this_week(d: Optional[date] = None) -> list[date]:
    """获取本周的交易日 (周一至周日)。"""
    if d is None:
        d = date.today()
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return trading_days_in_range(monday, sunday)


def trading_days_this_month(d: Optional[date] = None) -> list[date]:
    """获取本月的交易日。"""
    if d is None:
        d = date.today()
    first = d.replace(day=1)
    if d.month == 12:
        last = d.replace(year=d.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        last = d.replace(month=d.month + 1, day=1) - timedelta(days=1)
    return trading_days_in_range(first, last)


def market_open_time() -> dict:
    """A 股交易时间 (北京时间)。

    Returns:
        {"morning_open": "09:30", "morning_close": "11:30",
         "afternoon_open": "13:00", "afternoon_close": "15:00"}
    """
    return {
        "morning_open": "09:30",
        "morning_close": "11:30",
        "afternoon_open": "13:00",
        "afternoon_close": "15:00",
    }


def is_market_open(now: Optional[datetime] = None) -> bool:
    """判断当前是否在 A 股交易时段内。"""
    if now is None:
        now = datetime.now()

    if not is_trading_day(now.date()):
        return False

    t = now.time()
    from datetime import time as tclass
    return (
        (tclass(9, 30) <= t <= tclass(11, 30))
        or (tclass(13, 0) <= t <= tclass(15, 0))
    )


def today_str() -> str:
    """返回今天的日期字符串 YYYY-MM-DD。"""
    return date.today().strftime("%Y-%m-%d")
