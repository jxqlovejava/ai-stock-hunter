# -*- coding: utf-8 -*-
from src.indicators.chanlun.core.bihuang import detect_divergence
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


def test_bottom_divergence():
    bis = [_bi("down", 30, 20, area=100.0), _bi("up", 25, 18, area=30.0),
           _bi("down", 22, 15, area=50.0)]     # 低点15<20 且面积50<100
    div = detect_divergence(bis)
    assert 2 in div and div[2]["type"] == "bottom"


def test_top_divergence():
    bis = [_bi("up", 20, 10, area=100.0), _bi("down", 15, 8, area=30.0),
           _bi("up", 25, 12, area=60.0)]       # 高点25>20 且面积60<100
    div = detect_divergence(bis)
    assert 2 in div and div[2]["type"] == "top"


def test_no_divergence_when_force_grows():
    bis = [_bi("down", 30, 20, area=50.0), _bi("up", 25, 18, area=30.0),
           _bi("down", 22, 15, area=80.0)]     # 低点15<20 但面积80>50
    assert detect_divergence(bis) == {}
