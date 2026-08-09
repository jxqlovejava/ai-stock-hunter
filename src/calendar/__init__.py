"""A 股季节性风险日历。

借鉴自媒体博文《A股每年都有4个危险的时间窗口》（来源: 0x鸣人 @LuBtc888, T3 三级信源）。
默认为软性落地：WARN 军规 + 可配置仓位折扣 + 分析标注，经 backtest/seasonality.py 验证后再调强。
"""

from src.calendar.seasonal_windows import (
    DISCOUNT_FLOOR,
    SeasonalOverlay,
    SeasonalWindow,
    SeasonalWindowInfo,
    SeasonalWindowMeta,
    detect_seasonal_windows,
    disclosure_lateness_note,
    seasonal_flag_map,
    seasonal_risk_overlay,
)

__all__ = [
    "DISCOUNT_FLOOR",
    "SeasonalOverlay",
    "SeasonalWindow",
    "SeasonalWindowInfo",
    "SeasonalWindowMeta",
    "detect_seasonal_windows",
    "disclosure_lateness_note",
    "seasonal_flag_map",
    "seasonal_risk_overlay",
]
