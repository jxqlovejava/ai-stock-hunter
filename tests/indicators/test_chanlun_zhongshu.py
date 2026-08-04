# tests/indicators/test_chanlun_zhongshu.py
# -*- coding: utf-8 -*-
from src.indicators.chanlun.core.zhongshu import detect_zhongshus
from src.indicators.chanlun.schema import Bi, Fractal


def _bi(direction, high, low):
    if direction == "up":
        fx_a = Fractal(mark="D", dt=0, high=low + 1, low=low, fx=low, index=0)
        fx_b = Fractal(mark="G", dt=5, high=high, low=high - 1, fx=high, index=5)
    else:
        fx_a = Fractal(mark="G", dt=0, high=high, low=high - 1, fx=high, index=0)
        fx_b = Fractal(mark="D", dt=5, high=low + 1, low=low, fx=low, index=5)
    return Bi(direction=direction, start_fx=fx_a, end_fx=fx_b, high=high, low=low,
              length=5, macd_area=0.0, start_dt=0, end_dt=5)


def test_zhongshu_valid_overlap():
    bis = [_bi("up", 20, 10), _bi("down", 18, 12), _bi("up", 22, 15)]
    zss = detect_zhongshus(bis)
    assert len(zss) == 1
    zs = zss[0]
    assert zs.zg == 18.0     # min(20,18,22)
    assert zs.zd == 15.0     # max(10,12,15)
    assert zs.zg > zs.zd
    assert zs.state == "形成"


def test_no_overlap_no_zhongshu():
    bis = [_bi("up", 10, 1), _bi("down", 20, 11), _bi("up", 30, 21)]
    assert detect_zhongshus(bis) == []


def test_zhongshu_move_up_state():
    bis = [
        _bi("up", 18, 12), _bi("down", 16, 15), _bi("up", 17, 13),    # 中枢1 [15,16]
        _bi("up", 26, 21), _bi("down", 24, 22), _bi("up", 25, 23),    # 中枢2 [23,24]
    ]
    zss = detect_zhongshus(bis)
    assert len(zss) == 2
    assert zss[1].zd > zss[0].zg      # 23 > 16 → 上移
    assert zss[1].state == "上移"
