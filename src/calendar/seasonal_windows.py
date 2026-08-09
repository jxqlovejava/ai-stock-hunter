"""A 股季节性风险日历 (Seasonal Risk Calendar)。

借鉴自媒体博文《A股每年都有4个危险的时间窗口》（来源: 0x鸣人 @LuBtc888, T3 三级信源）：

1. YEAR_END_LIQUIDITY  12月中下旬-1月初 流动性枯竭窗口
   （银行年终结算资金回笼 / 公募锁定排名 / 私募应对赎回被动卖出 / 游资休息）
2. APRIL_EARNINGS      4月底 财报业绩双杀窗口
   （年报 + 一季报披露截止 4/30，拖到最后披露的公司非雷即坑，可能戴维斯双杀）
3. AUGUST_INTERIM      8月底 中报预期证伪窗口
   （上半年靠预期和故事炒，中报落地检验故事真假，证伪 → 机构杀估值）
4. OCTOBER_RETAIL      10月底 季末获利了结窗口
   （三季报后全年业绩大局已定，机构为保年终奖调仓换股/兑现离场）

来源等级 T3（自媒体断言），故默认软性落地：WARN 军规 + 轻折扣 + 分析标注。

回测验证结论（backtest/seasonality.py，沪深300 2002-2026 前视5日）：
  - 年末流动性枯竭窗口  窗口均值 +0.55% vs 基线 +0.17%  → ❌ 指数层面不危险（甚至跑赢）
  - 财报业绩双杀窗口  胜率 46.3% vs 基线 52.5%        → ⚠️ 弱支持
  - 中报证伪窗口 / 季末获利了结窗口                      → ❌ 指数层面无显著效应
  注: 断言针对"题材股/非核心主线"个股而非指数，指数层面不显著不代表个股层面无效；
  故保留为软提示（WARN + 轻折扣），不作强约束。
核心函数均为纯日期逻辑、无网络依赖，可单元测试。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# 多窗口叠加时折扣下限，防止过度扣减
DISCOUNT_FLOOR = 0.60


class SeasonalWindow(str, Enum):
    """A 股季节性危险窗口。"""

    YEAR_END_LIQUIDITY = "YEAR_END_LIQUIDITY"  # 12月中下旬-1月初 流动性枯竭
    APRIL_EARNINGS = "APRIL_EARNINGS"  # 4月底 年报+一季报业绩双杀
    AUGUST_INTERIM = "AUGUST_INTERIM"  # 8月底 中报预期证伪
    OCTOBER_RETAIL = "OCTOBER_RETAIL"  # 10月底 季末获利了结


# 日期区间：(起始月,起始日) -> (结束月,结束日)。跨年窗口用 (12,15) -> (1,10) 表示。
_WINDOW_RANGES: dict[SeasonalWindow, tuple[tuple[int, int], tuple[int, int]]] = {
    SeasonalWindow.YEAR_END_LIQUIDITY: ((12, 15), (1, 10)),
    SeasonalWindow.APRIL_EARNINGS: ((4, 15), (4, 30)),
    SeasonalWindow.AUGUST_INTERIM: ((8, 20), (8, 31)),
    SeasonalWindow.OCTOBER_RETAIL: ((10, 20), (10, 31)),
}

@dataclass
class SeasonalWindowMeta:
    """窗口元信息 DTO（替代裸 dict，遵循 DTO 优先）。"""

    name: str
    logic: str
    action: str
    discount: float
    confidence: float


# 窗口元信息：名称 / 驱动逻辑 / 应对动作 / 仓位折扣 / 置信度
_WINDOW_META: dict[SeasonalWindow, SeasonalWindowMeta] = {
    SeasonalWindow.YEAR_END_LIQUIDITY: SeasonalWindowMeta(
        name="年末流动性枯竭窗口",
        logic=(
            "银行年终结算资金回笼 + 公募锁定排名按兵不动 + "
            "私募应对赎回被动卖出 + 游资休息分红过年 → 真空期只有卖盘没有买盘"
        ),
        action="12月15日后非核心主线清仓；每根阳线大概率是诱多出货陷阱，不博跨年妖股",
        discount=0.90,  # 回测显示指数层面 12 月反而跑赢基线，仅轻折扣
        confidence=0.55,
    ),
    SeasonalWindow.APRIL_EARNINGS: SeasonalWindowMeta(
        name="财报业绩双杀窗口",
        logic=(
            "4/30 是年报与一季报披露截止日，好学生抢着交卷、差生拖到最后；"
            "年报不好叠加一季报亏损 → 戴维斯双杀，散户抄底易抄进退市名单"
        ),
        action="4月中旬起回避尚未披露业绩的题材股，尤其炒作过高、市盈率高得离谱、无业绩支撑的",
        discount=0.85,
        confidence=0.60,
    ),
    SeasonalWindow.AUGUST_INTERIM: SeasonalWindowMeta(
        name="中报证伪窗口",
        logic=(
            "上半年行情靠预期和故事炒起来，8月底中报是检验故事真假、"
            "能否变成真金白银的试金石；业绩频频/亏损 → 逻辑证伪 → 机构不计成本出货杀估值"
        ),
        action="8月下旬去弱留强，只做业绩超预期的真龙头，跟风杂毛股提前一月清理",
        discount=0.95,  # 指数层面无显著效应，仅轻微提示
        confidence=0.55,
    ),
    SeasonalWindow.OCTOBER_RETAIL: SeasonalWindowMeta(
        name="季末获利了结窗口",
        logic=(
            "10月底三季报披露完，全年业绩大局已定；机构为保住年终奖，"
            "11月前大规模调仓换股/兑现离场 → 主力主动性撤退，杀伤力大"
        ),
        action="10月底不赌反弹，主力撤退时进场就是接盘；可空仓等年底调整结束",
        discount=0.95,  # 指数层面无显著效应，仅轻微提示
        confidence=0.55,
    ),
}


@dataclass
class SeasonalWindowInfo:
    """单个活跃的季节窗口信息。"""

    window: SeasonalWindow
    name: str
    logic: str
    action: str
    discount: float
    start_date: date
    end_date: date
    confidence: float


@dataclass
class SeasonalOverlay:
    """季节性风险叠加层：多窗口折扣乘积 + 活跃窗口 + 提示 notes。"""

    discount: float = 1.0
    active_windows: list[SeasonalWindowInfo] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _window_bounds(today: date, window: SeasonalWindow) -> tuple[date, date]:
    """返回窗口在当前年份的起止日期（跨年窗口正确处理 1 月初属于上一年的 12/15 起）。"""
    (sm, sd), (em, ed) = _WINDOW_RANGES[window]
    if window == SeasonalWindow.YEAR_END_LIQUIDITY:
        if today.month == 12:
            return date(today.year, sm, sd), date(today.year + 1, em, ed)
        # 1 月 1-10 日属于上一年的年末窗口
        return date(today.year - 1, sm, sd), date(today.year, em, ed)
    return date(today.year, sm, sd), date(today.year, em, ed)


def _in_window(today: date, window: SeasonalWindow) -> bool:
    """判断 today 是否落在给定窗口内（纯日期比较）。"""
    m, d = today.month, today.day
    (sm, sd), (em, ed) = _WINDOW_RANGES[window]
    if window == SeasonalWindow.YEAR_END_LIQUIDITY:
        return (m == 12 and d >= sd) or (m == 1 and d <= ed)
    return (m, d) >= (sm, sd) and (m, d) <= (em, ed)


def detect_seasonal_windows(today: Optional[date] = None) -> list[SeasonalWindowInfo]:
    """检测当前日期处于哪些季节性危险窗口。纯日期逻辑，无网络。"""
    today = today or date.today()
    active: list[SeasonalWindowInfo] = []
    for window in SeasonalWindow:
        if not _in_window(today, window):
            continue
        meta = _WINDOW_META[window]
        start, end = _window_bounds(today, window)
        active.append(
            SeasonalWindowInfo(
                window=window,
                name=meta.name,
                logic=meta.logic,
                action=meta.action,
                discount=meta.discount,
                start_date=start,
                end_date=end,
                confidence=meta.confidence,
            )
        )
    return active


def seasonal_risk_overlay(today: Optional[date] = None) -> SeasonalOverlay:
    """计算季节性风险叠加层：折扣乘积（下限 DISCOUNT_FLOOR）+ 活跃窗口 + notes。"""
    windows = detect_seasonal_windows(today)
    if not windows:
        return SeasonalOverlay()
    discount = 1.0
    for w in windows:
        discount *= w.discount
    discount = max(discount, DISCOUNT_FLOOR)
    notes = [
        f"[季节性] {w.name}（{w.start_date.month}/{w.start_date.day}-{w.end_date.month}/{w.end_date.day}）: {w.action}"
        for w in windows
    ]
    return SeasonalOverlay(
        discount=round(discount, 2), active_windows=windows, notes=notes
    )


def seasonal_flag_map(today: Optional[date] = None) -> dict[str, bool]:
    """军规 ctx 用的 4 个布尔 flag（r051-r054）。"""
    active = {w.window for w in detect_seasonal_windows(today)}
    return {
        "seasonal_year_end_window": SeasonalWindow.YEAR_END_LIQUIDITY in active,
        "seasonal_april_window": SeasonalWindow.APRIL_EARNINGS in active,
        "seasonal_august_window": SeasonalWindow.AUGUST_INTERIM in active,
        "seasonal_october_window": SeasonalWindow.OCTOBER_RETAIL in active,
    }


def disclosure_lateness_note(
    symbol: str, today: Optional[date] = None
) -> Optional[str]:
    """财报披露日期越晚越雷（自媒体断言，T3）。

    仅在 4 月业绩双杀窗口内生效：若能从业绩预告/快报事件推断该股今年尚未披露
    一季报/年报（最近披露事件距今 > 45 天），返回提示 note。
    数据拿不到/取不到 → 返回 None（DATA_GAP，不做任何调整）。绝不抛异常。
    """
    today = today or date.today()
    if not _in_window(today, SeasonalWindow.APRIL_EARNINGS):
        return None
    try:
        from src.data.financial_statements import _get_earnings_events

        events = _get_earnings_events(symbol) or []
        if not events:
            return None
        latest = None
        for e in events:
            d = getattr(e, "date", None) or getattr(e, "disclosure_date", None)
            if d:
                latest = max(latest, d) if latest else d
        if latest is None:
            return None
        if (today - latest).days > 45:
            return (
                f"[季节性] {symbol} 近 45 天无业绩披露事件——4月窗口内越晚披露雷概率越高"
                "（自媒体断言 T3，仅作风险提示）"
            )
        return None
    except Exception as exc:  # noqa: BLE001 - 尽力而为，绝不让披露提示拖垮分析
        logger.debug("disclosure_lateness_note(%s): %s", symbol, exc)
        return None
