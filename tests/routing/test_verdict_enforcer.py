# -*- coding: utf-8 -*-
"""VerdictEnforcer._compute_price_range 买点可达性测试 (2026-08-08).

背景: 原 buy_below 锚定现价 15-30% 折扣 → 上涨趋势中结构性不可达。
修复: 优先用 quote_dict 携带的技术支撑 (ma20/ma60/close_series) 做可达买点,
估值安全边际降为 valuation_buy (理想价参考)。

纯函数/快照级测试, 不触发网络。
"""
import pytest

from src.routing.verdict_enforcer import VerdictEnforcer


def _compute(quote: dict):
    return VerdictEnforcer._compute_price_range("600089", quote, None)


# ── 场景①: 上涨趋势, 技术支撑在现价附近 → 可达 ──
def test_uptrend_support_reachable():
    pr = _compute({
        "price": 21.33, "pe_ttm": 17.5,
        "ma20": 20.5, "ma60": 19.8,
        "close_series": [20.1, 20.3, 20.2, 20.5, 20.6, 20.4, 20.7, 20.8, 20.9, 21.0],
    })
    assert pr.reachable is True
    assert pr.buy_below == 20.5          # = ma20 支撑
    assert pr.buy_max <= pr.current_price  # 最高买价不高于现价
    assert pr.buy_max >= pr.current_price * 0.98  # 距现价近, 可达
    # 估值安全边际保留为理想价
    assert pr.valuation_buy == round(21.33 * 0.85, 2)


# ── 场景②: 无技术数据 → 回退估值折扣, 不可达 ──
def test_no_technical_falls_back_to_discount():
    pr = _compute({"price": 21.33, "pe_ttm": 17.5})
    assert pr.reachable is False
    assert pr.buy_below == round(21.33 * 0.85, 2)  # 回退到 15% 折扣
    assert pr.valuation_buy == pr.buy_below


# ── 场景③: 现价远离支撑 (暴涨) → 不可达 ──
def test_extended_price_marked_unreachable():
    pr = _compute({
        "price": 34.23, "pe_ttm": 25.0,
        "ma20": 30.0, "ma60": 26.0,
        "close_series": [29, 29.5, 30, 30.5, 31, 31.5, 32, 32.5, 33, 34],
    })
    assert pr.reachable is False           # ma20 距现价 12.4% > 10%
    assert pr.buy_below == 30.0            # 仍给支撑参考 (优于固定折扣)
    assert pr.valuation_buy == round(34.23 * 0.85, 2)  # PE25(<30) → 15% 折扣


# ── 场景④: 支撑恰在现价下方一点 → 可达, buy_below 距现价 ≤ 10% ──
def test_support_just_below_price_reachable():
    pr = _compute({
        "price": 20.0, "pe_ttm": 20.0,
        "ma20": 19.2, "ma60": 18.5,
        "close_series": [18.8, 18.9, 19.0, 19.1, 19.2, 19.1, 19.3, 19.4, 19.5, 19.9],
    })
    assert pr.reachable is True
    assert (pr.buy_below / pr.current_price - 1) > -0.10  # 距现价 4% → 可达


# ── 场景⑤: 支撑在现价上方 (强趋势无参考) → 回退不可达 ──
def test_support_above_price_falls_back():
    pr = _compute({
        "price": 18.0, "pe_ttm": 22.0,
        "ma20": 19.0, "ma60": 18.8,  # ma 高于现价 → 无下方支撑
        "close_series": [18.5, 18.6, 18.7, 18.8, 18.9, 19.0, 18.9, 18.8, 18.7, 18.6],
    })
    # 无 ≤现价×1.02 的支撑 → 回退估值折扣
    assert pr.reachable is False
    assert pr.buy_below == round(18.0 * 0.85, 2)
