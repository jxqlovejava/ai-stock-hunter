# -*- coding: utf-8 -*-
"""JobScheduler — cron/at/every 调度解析与到期判断。"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional
from zoneinfo import ZoneInfo

from .types import CronJob, JobState

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# croniter 可选依赖
# ------------------------------------------------------------------

_HAS_CRONITER = False
try:
    import croniter  # noqa: F401

    _HAS_CRONITER = True
except ImportError:
    pass

# ------------------------------------------------------------------
# 默认时区
# ------------------------------------------------------------------

_DEFAULT_TZ = "Asia/Shanghai"


def _get_tz(tz_name: str | None = None) -> tzinfo:
    return ZoneInfo(tz_name or _DEFAULT_TZ)


# ======================================================================
# Cron 表达式解析
# ======================================================================


def parse_cron(expression: str, tz_name: Optional[str] = None) -> dict:
    """解析 cron 表达式，返回结构化信息。

    支持标准 5 字段:  minute hour day-of-month month day-of-week

    返回:
        {
            "raw":      str,
            "fields":   [minute, hour, dom, month, dow],
            "valid":    bool,
            "error":    str | None,
            "human":    str,  # 可读描述
        }
    """
    result: dict = {
        "raw": expression,
        "fields": [],
        "valid": False,
        "error": None,
        "human": "",
    }

    parts = expression.strip().split()
    if len(parts) != 5:
        result["error"] = f"Expected 5 fields, got {len(parts)}"
        return result

    # 检查每个字段合法性
    field_names = ["minute", "hour", "day-of-month", "month", "day-of-week"]
    for i, (part, name) in enumerate(zip(parts, field_names)):
        if not _is_valid_cron_field(part, i):
            result["error"] = f"Invalid {name} field: '{part}'"
            return result

    result["fields"] = parts
    result["valid"] = True
    result["human"] = _describe_cron(parts)
    return result


def _is_valid_cron_field(part: str, field_index: int) -> bool:
    """判断 cron 单字段是否合法。

    支持: *, */N, N-M, N-M/S, 逗号组合, 固定数值
    """
    # 允许的数值范围
    ranges = [
        (0, 59),  # minute
        (0, 23),  # hour
        (1, 31),  # day-of-month
        (1, 12),  # month
        (0, 7),  # day-of-week (0/7 = Sunday)
    ]
    low, high = ranges[field_index]

    for segment in part.split(","):
        segment = segment.strip()
        if not segment:
            return False

        # */N 或 N-M/S
        if "/" in segment:
            base, step = segment.split("/", 1)
            if not step.isdigit() or int(step) < 1:
                return False
            if base == "*":
                continue
            # N-M/S
            if "-" in base:
                parts_range = base.split("-", 1)
                if not _is_valid_int_range(parts_range, low, high):
                    return False
            elif base.isdigit():
                if not (low <= int(base) <= high):
                    return False
            else:
                return False
        # N-M
        elif "-" in segment:
            parts_range = segment.split("-", 1)
            if not _is_valid_int_range(parts_range, low, high):
                return False
        # *
        elif segment == "*":
            continue
        # 固定值
        elif segment.isdigit():
            val = int(segment)
            # 星期天允许 0 和 7
            if field_index == 4 and val in (0, 7):
                continue
            if not (low <= val <= high):
                return False
        else:
            return False

    return True


def _is_valid_int_range(parts: list[str], low: int, high: int) -> bool:
    if len(parts) != 2:
        return False
    a, b = parts
    if not a.isdigit() or not b.isdigit():
        return False
    na, nb = int(a), int(b)
    return low <= na <= nb <= high


def _describe_cron(fields: list[str]) -> str:
    """将 cron 5 字段转换为可读描述。"""
    m, h, dom, mon, dow = fields

    parts: list[str] = []

    # 星期
    day_names = ["周日", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    if dow == "*":
        parts.append("每天")
    elif "," in dow:
        days = [day_names[int(d)] for d in dow.split(",") if d.isdigit()]
        parts.append("每周" + "、".join(days))
    elif "-" in dow:
        a, b = dow.split("-", 1)
        if a.isdigit() and b.isdigit():
            days = [day_names[int(d)] for d in range(int(a), int(b) + 1)]
            parts.append("每周" + "、".join(days))
    elif dow.isdigit():
        parts.append(f"每周{day_names[int(dow)]}")

    # 月中的天
    if dom != "*":
        parts.append(f"第{dom}天")

    # 月
    if mon != "*":
        parts.append(f"{mon}月")

    # 时间描述
    time_desc = _describe_time(m, h)
    if time_desc:
        parts.append(time_desc)

    return " ".join(parts) if parts else expression


def _describe_time(minute_field: str, hour_field: str) -> str:
    """将 cron 的分和时字段转为可读描述。"""
    # */N pattern for minute (e.g. */15 -> "每15分")
    if minute_field.startswith("*/") and hour_field == "*":
        interval = minute_field.split("/")[1]
        return f"每{interval}分钟"

    if minute_field.startswith("*/") and hour_field.isdigit():
        interval = minute_field.split("/")[1]
        return f"每{interval}分（{int(hour_field):02d}点起）"

    # */N pattern for hour (e.g. */2 -> "每2小时")
    if hour_field.startswith("*/"):
        interval = hour_field.split("/")[1]
        return f"每{interval}小时"

    # 固定小时
    if hour_field == "*":
        if minute_field == "0":
            return "每小时整点"
        if minute_field.isdigit():
            return f"每小时{int(minute_field):02d}分"
        return ""

    # 小时范围（如 9-17）
    if "-" in hour_field:
        parts_range = hour_field.split("-", 1)
        if parts_range[0].isdigit() and parts_range[1].isdigit():
            start_h, end_h = int(parts_range[0]), int(parts_range[1])
            if minute_field == "0":
                return f"{start_h:02d}:00-{end_h:02d}:00"
            if minute_field.isdigit():
                return f"{start_h:02d}:{int(minute_field):02d}-{end_h:02d}:{int(minute_field):02d}"
            if minute_field.startswith("*/"):
                interval = minute_field.split("/")[1]
                return f"{start_h:02d}:00-{end_h:02d}:00 每{interval}分"
            return f"{start_h}-{end_h}点 {minute_field}分"
        return ""

    # 逗号分隔的小时值
    if "," in hour_field:
        hours = hour_field.split(",")
        return f"在{','.join(hours)}点 {minute_field}分"

    # 单个小时值
    if hour_field.isdigit():
        hour = int(hour_field)
        if minute_field == "0":
            return f"{hour:02d}:00"
        if minute_field.isdigit():
            return f"{hour:02d}:{int(minute_field):02d}"
        if minute_field.startswith("*/"):
            interval = minute_field.split("/")[1]
            return f"每{interval}分（{hour:02d}点起）"
        return f"{hour:02d}点{minute_field}分"

    return f"{hour_field}:{minute_field}"


# ======================================================================
# At / Every 解析
# ======================================================================


def parse_at(datetime_str: str) -> Optional[datetime]:
    """解析一次性调度的时间点。

    支持格式:
      - ISO: "2026-07-08T15:00:00+08:00"
      - 无时区: "2026-07-08 15:00" (视为 Asia/Shanghai)
      - 只有HH:MM: "15:00" (视为当天)
    """
    dt_str = datetime_str.strip()

    # 尝试完整 ISO
    try:
        return datetime.fromisoformat(dt_str)
    except ValueError:
        pass

    # 尝试 "YYYY-MM-DD HH:MM"
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(dt_str, fmt)
            return dt.replace(tzinfo=_get_tz())
        except ValueError:
            continue

    # 尝试只有 "HH:MM" — 视为当天
    try:
        tm = datetime.strptime(dt_str, "%H:%M")
        now = datetime.now(_get_tz())
        dt = now.replace(hour=tm.hour, minute=tm.minute, second=0, microsecond=0)
        # 如果已过则推到明天
        if dt <= now:
            dt += timedelta(days=1)
        return dt
    except ValueError:
        pass

    return None


def parse_every(interval_ms: int) -> timedelta:
    """将毫秒间隔转换为 timedelta。"""
    return timedelta(milliseconds=interval_ms)


# ======================================================================
# 到期判断
# ======================================================================


def _get_next_cron_run(expression: str, after: datetime) -> Optional[datetime]:
    """计算给定 cron 表达式在 after 后的下次触发时间。

    优先使用 croniter，不可用时使用简单线性扫描。
    """
    if _HAS_CRONITER:
        try:
            cron_obj = croniter.croniter(expression, after)
            return cron_obj.get_next(datetime)
        except Exception as exc:
            logger.debug("croniter failed: %s", exc)

    # Fallback: 简单逐分钟扫描（最多向前看 7 天）
    result = parse_cron(expression)
    if not result["valid"]:
        return None

    fields = result["fields"]
    dt = after.replace(second=0, microsecond=0)
    deadline = after + timedelta(days=7)

    while dt <= deadline:
        if _cron_matches(dt, fields):
            return dt
        dt += timedelta(minutes=1)

    return None


def _cron_matches(dt: datetime, fields: list[str]) -> bool:
    """检查 datetime 是否匹配 cron 字段。"""
    minute, hour, dom, month, dow = fields
    m, h, d, mo, w = dt.minute, dt.hour, dt.day, dt.month, dt.weekday()

    # 星期天处理：Python weekday() 0=Mon,6=Sun; cron 0/7=Sun
    w_cron = w + 1  # 1=Mon,7=Sun
    if w_cron == 7:
        w_cron = 0  # cron 允许 0 表示周日

    return (
        _field_matches(m, minute, 0, 59)
        and _field_matches(h, hour, 0, 23)
        and _field_matches(d, dom, 1, 31)
        and _field_matches(mo, month, 1, 12)
        and _field_matches(w_cron, dow, 0, 7)
    )


def _field_matches(value: int, pattern: str, low: int, high: int) -> bool:
    """判断单个数值是否匹配 cron 字段模式。"""
    for segment in pattern.split(","):
        segment = segment.strip()
        if segment == "*":
            return True
        if "/" in segment:
            base, step = segment.split("/", 1)
            step_int = int(step)
            if base == "*":
                if (value - low) % step_int == 0:
                    return True
            elif "-" in base:
                a, b = base.split("-", 1)
                if int(a) <= value <= int(b) and (value - int(a)) % step_int == 0:
                    return True
            else:
                if int(base) == value:
                    return True
        elif "-" in segment:
            a, b = segment.split("-", 1)
            if int(a) <= value <= int(b):
                return True
        elif segment.isdigit():
            seg_val = int(segment)
            # day-of-week: 0 and 7 both mean Sunday
            if low == 0 and high == 7 and seg_val == 7 and value == 0:
                return True
            if seg_val == value:
                return True
    return False


# ======================================================================
# 活跃窗口判断
# ======================================================================


def is_in_active_window(job: CronJob, now: Optional[datetime] = None) -> bool:
    """检查当前时间是否在任务的活跃窗口内。"""
    if now is None:
        now = datetime.now(_get_tz())

    # 活跃天
    if job.active_days is not None:
        today = now.weekday()  # 0=Mon, 6=Sun
        # cron.day-of-week convention: 0=Sun, 1=Mon, ..., 6=Sat
        # Python: 0=Mon, 6=Sun -> convert to cron convention
        today_cron = (today + 1) % 7  # 0=Sun, 1=Mon, ..., 6=Sat
        if today_cron not in job.active_days:
            return False

    # 活跃时间段
    if job.active_window_start and job.active_window_end:
        try:
            start_tm = datetime.strptime(job.active_window_start, "%H:%M").time()
            end_tm = datetime.strptime(job.active_window_end, "%H:%M").time()
            current = now.time()

            if start_tm <= end_tm:
                if not (start_tm <= current <= end_tm):
                    return False
            else:
                # 跨天（如 22:00 - 06:00）
                if current < start_tm and current > end_tm:
                    return False
        except ValueError:
            logger.warning("Invalid active_window time format: %s/%s",
                           job.active_window_start, job.active_window_end)

    return True


# ======================================================================
# 主调度器
# ======================================================================


class JobScheduler:
    """定时任务调度引擎。"""

    def __init__(self, timezone: str = _DEFAULT_TZ) -> None:
        self._tz_name = timezone
        self._tz = _get_tz(timezone)

    @property
    def timezone(self) -> str:
        return self._tz_name

    # ------------------------------------------------------------------
    # 到期判断
    # ------------------------------------------------------------------

    @property
    def tz(self) -> tzinfo:
        """调度器使用的时区对象。"""
        return self._tz

    def now(self) -> datetime:
        """返回当前时区感知的时间。"""
        return datetime.now(self._tz)

    def is_due(self, job: CronJob, now: Optional[datetime] = None) -> bool:
        """判断任务是否到期需要执行。

        需满足:
          1. enabled + state=ACTIVE
          2. 在活跃窗口内（如有设置）
          3. 调度条件满足
        """
        if now is None:
            now = datetime.now(self._tz)

        if not job.enabled or job.state != JobState.ACTIVE:
            return False

        if not is_in_active_window(job, now):
            return False

        return self._schedule_due(job, now)

    def _schedule_due(self, job: CronJob, now: datetime) -> bool:
        """根据调度类型判断是否到期。"""
        if job.schedule_type == "at":
            return self._at_due(job, now)
        elif job.schedule_type == "every":
            return self._every_due(job, now)
        elif job.schedule_type == "cron":
            return self._cron_due(job, now)
        else:
            logger.warning("Unknown schedule_type: %s", job.schedule_type)
            return False

    def _at_due(self, job: CronJob, now: datetime) -> bool:
        target = parse_at(job.schedule_value)
        if target is None:
            return False
        # 一次性任务: 过去 60 秒内到期
        if job.last_run_at:
            return False  # 已执行过
        return abs((now - target).total_seconds()) <= 60

    def _every_due(self, job: CronJob, now: datetime) -> bool:
        try:
            interval = int(job.schedule_value)
        except (ValueError, TypeError):
            return False

        if not job.last_run_at:
            return True  # 从未运行

        try:
            last = datetime.fromisoformat(job.last_run_at)
        except ValueError:
            return True

        return (now - last).total_seconds() * 1000 >= interval

    def _cron_due(self, job: CronJob, now: datetime) -> bool:
        if not job.last_run_at:
            return True  # 从未运行

        try:
            last = datetime.fromisoformat(job.last_run_at)
        except ValueError:
            return True

        # 检查从现在到上次运行之间是否有匹配的触发点
        # 简单策略: 上次运行后 60 秒内不重复
        if (now - last).total_seconds() < 60:
            return False

        # 查看上次运行到现在之间是否有到期时间
        next_dt = _get_next_cron_run(job.schedule_value, last)
        if next_dt is None:
            return False
        return next_dt <= now

    # ------------------------------------------------------------------
    # 下次运行时间
    # ------------------------------------------------------------------

    def next_run(self, job: CronJob, after: Optional[datetime] = None) -> Optional[str]:
        """计算任务的下次触发时间（ISO 字符串）。"""
        if after is None:
            after = datetime.now(self._tz)

        if not job.enabled or job.state not in (JobState.ACTIVE,):
            return None

        if job.schedule_type == "at":
            target = parse_at(job.schedule_value)
            if target and target > after:
                return target.isoformat()
            return None

        elif job.schedule_type == "every":
            try:
                interval = int(job.schedule_value)
            except (ValueError, TypeError):
                return None
            if job.last_run_at:
                try:
                    last = datetime.fromisoformat(job.last_run_at)
                    next_dt = last + timedelta(milliseconds=interval)
                except ValueError:
                    next_dt = after
            else:
                next_dt = after
            return next_dt.isoformat() if next_dt > after else None

        elif job.schedule_type == "cron":
            last = after
            if job.last_run_at:
                try:
                    last = datetime.fromisoformat(job.last_run_at)
                except ValueError:
                    pass
            next_dt = _get_next_cron_run(job.schedule_value, last)
            if next_dt:
                return next_dt.isoformat()
            return None

        return None
