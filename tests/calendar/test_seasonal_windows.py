"""季节性风险日历纯逻辑测试（无网络）。"""

from datetime import date

from src.calendar.seasonal_windows import (
    DISCOUNT_FLOOR,
    SeasonalWindow,
    detect_seasonal_windows,
    seasonal_flag_map,
    seasonal_risk_overlay,
)


def test_year_end_window_december():
    """12月下旬 → 年末流动性枯竭窗口。"""
    windows = detect_seasonal_windows(date(2026, 12, 20))
    names = {w.window for w in windows}
    assert SeasonalWindow.YEAR_END_LIQUIDITY in names
    assert len(names) == 1


def test_year_end_window_january_cross_year():
    """1月初属于上一年的年末窗口（跨年）。"""
    windows = detect_seasonal_windows(date(2027, 1, 5))
    names = {w.window for w in windows}
    assert SeasonalWindow.YEAR_END_LIQUIDITY in names
    # 区间起点是上一年的 12/15
    w = next(x for x in windows if x.window == SeasonalWindow.YEAR_END_LIQUIDITY)
    assert w.start_date.year == 2026
    assert w.start_date.month == 12


def test_april_window():
    windows = detect_seasonal_windows(date(2026, 4, 25))
    assert {w.window for w in windows} == {SeasonalWindow.APRIL_EARNINGS}


def test_august_window():
    windows = detect_seasonal_windows(date(2026, 8, 25))
    assert {w.window for w in windows} == {SeasonalWindow.AUGUST_INTERIM}


def test_october_window():
    windows = detect_seasonal_windows(date(2026, 10, 25))
    assert {w.window for w in windows} == {SeasonalWindow.OCTOBER_RETAIL}


def test_no_window_in_quiet_month():
    """7月中旬不处于任何窗口。"""
    assert detect_seasonal_windows(date(2026, 7, 15)) == []


def test_window_boundaries_inclusive():
    """边界日期包含（12/15 起、1/10 止）。"""
    assert detect_seasonal_windows(date(2026, 12, 15))  # 起
    assert detect_seasonal_windows(date(2027, 1, 10))  # 止
    assert detect_seasonal_windows(date(2027, 1, 11)) == []  # 止后


def test_risk_overlay_discount_product_and_floor():
    """折扣为活跃窗口乘积，且不低于下限。"""
    # 单窗口: 12月折扣 0.90（回测后调弱）
    overlay = seasonal_risk_overlay(date(2026, 12, 20))
    assert overlay.discount == 0.90
    assert len(overlay.active_windows) == 1
    assert overlay.notes
    # 无窗口: 折扣 1.0
    assert seasonal_risk_overlay(date(2026, 7, 15)).discount == 1.0
    # 4月窗口保留 0.85（回测弱支持）
    assert seasonal_risk_overlay(date(2026, 4, 25)).discount == 0.85
    # 折扣下限兜底
    assert DISCOUNT_FLOOR <= 0.85


def test_flag_map_matches_windows():
    """军规 ctx flag 与窗口检测一致。"""
    flags = seasonal_flag_map(date(2026, 4, 25))
    assert flags == {
        "seasonal_year_end_window": False,
        "seasonal_april_window": True,
        "seasonal_august_window": False,
        "seasonal_october_window": False,
    }
    # 无窗口月份全 False
    flags = seasonal_flag_map(date(2026, 7, 15))
    assert all(v is False for v in flags.values())
