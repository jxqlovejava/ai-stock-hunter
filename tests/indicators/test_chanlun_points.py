# -*- coding: utf-8 -*-
from src.indicators.chanlun.core.zhongshu import detect_zhongshus
from src.indicators.chanlun.points import detect_points
from src.indicators.chanlun.schema import Bi, Fractal


def _bi(direction, high, low, area=0.0):
    if direction == "up":
        fa, fb = Fractal(mark="D", dt=0, high=low + 1, low=low, fx=low, index=0), \
                 Fractal(mark="G", dt=5, high=high, low=high - 1, fx=high, index=5)
    else:
        fa, fb = Fractal(mark="G", dt=0, high=high, low=high - 1, fx=high, index=0), \
                 Fractal(mark="D", dt=5, high=low + 1, low=low, fx=low, index=5)
    return Bi(direction=direction, start_fx=fa, end_fx=fb, high=high, low=low,
              length=5, macd_area=area, start_dt=0, end_dt=5)


def test_first_buy_and_second_buy():
    # 中枢1 [32,35] + 末段底背驰 → 一买(24) → 回调不破 → 二买(25)
    bis = [
        _bi("down", 40, 30, area=100.0), _bi("up", 36, 32, area=30.0),
        _bi("down", 35, 31, area=80.0),   # 中枢 [min40,36,35=35, max30,32,31=32]
        _bi("up", 34, 33, area=20.0),
        _bi("down", 30, 24, area=40.0),   # 低点24<31 且 40<80 → 底背驰 → 一买@24
        _bi("up", 30, 26, area=20.0),
        _bi("down", 27, 25, area=30.0),   # 低点25>24 不破一买低点 → 二买@25
    ]
    zss = detect_zhongshus(bis)
    points = detect_points(bis, zss, {4: {"type": "bottom", "bi_index": 4}})
    kinds = [p.kind for p in points]
    assert "一买" in kinds and "二买" in kinds
    assert any(p.kind == "二买" and p.price == 25.0 for p in points)


def test_third_buy_after_breakout():
    bis = [
        _bi("down", 40, 30), _bi("up", 36, 32), _bi("down", 35, 31),   # 中枢 [32,35]
        _bi("up", 40, 33),                                             # 突破 zg=35
        _bi("down", 38, 36),                                           # 回抽低点36>35 → 三买
    ]
    zss = detect_zhongshus(bis)
    points = detect_points(bis, zss, {})
    assert any(p.kind == "三买" and p.price == 36.0 for p in points)


def test_first_sell_and_second_sell_mirror():
    bis = [
        _bi("up", 20, 10, area=100.0), _bi("down", 16, 12, area=30.0),
        _bi("up", 22, 15, area=80.0),   # 中枢 [16,20]
        _bi("down", 17, 13, area=20.0),
        _bi("up", 28, 20, area=40.0),   # 高点28>22 且 40<80 → 顶背驰 → 一卖@28
        _bi("down", 24, 18, area=20.0),
        _bi("up", 27, 21, area=30.0),   # 高点27<28 不破一卖高点 → 二卖@27
    ]
    zss = detect_zhongshus(bis)
    points = detect_points(bis, zss, {4: {"type": "top", "bi_index": 4}})
    kinds = [p.kind for p in points]
    assert "一卖" in kinds and "二卖" in kinds
