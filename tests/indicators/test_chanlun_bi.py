# -*- coding: utf-8 -*-
from src.indicators.chanlun.core.bi import build_bis
from src.indicators.chanlun.schema import Fractal


def _fx(mark, index, fx):
    if mark == "G":
        return Fractal(mark="G", dt=index, high=fx, low=fx - 1, fx=fx, index=index)
    return Fractal(mark="D", dt=index, high=fx + 1, low=fx, fx=fx, index=index)


def test_build_bis_alternates():
    fs = [_fx("D", 0, 10), _fx("G", 5, 20), _fx("D", 10, 12), _fx("G", 16, 25)]
    bis = build_bis(fs, min_len=4)
    assert len(bis) == 3
    assert [b.direction for b in bis] == ["up", "down", "up"]


def test_bi_min_length_rejected():
    fs = [_fx("D", 0, 10), _fx("G", 2, 20)]   # gap=2 < 4
    assert build_bis(fs, min_len=4) == []


def test_consecutive_same_mark_keeps_extreme():
    fs = [_fx("D", 0, 10), _fx("G", 5, 20), _fx("G", 7, 25), _fx("D", 12, 15)]
    bis = build_bis(fs, min_len=4)
    assert len(bis) == 2
    assert bis[0].end_fx.fx == 25          # 保留更高的顶
    assert bis[0].direction == "up" and bis[1].direction == "down"


def test_bi_high_low_from_endpoints():
    fs = [_fx("D", 0, 10), _fx("G", 5, 20)]
    bis = build_bis(fs, min_len=4)
    assert bis[0].high == 20.0 and bis[0].low == 10.0
    assert bis[0].start_fx.mark == "D" and bis[0].end_fx.mark == "G"


def test_no_consecutive_same_direction_after_swallow():
    # 回归 Bug2: 旧顶 G(20)@5 被新高 G(30)@12 吞没（中间小回调 D(15)@7 与两者过近）。
    # 贪心版会产出 [D→G(20), D→G(30)] 两根同向上行笔；迭代版应吸收为 1 根且严格交替。
    fs = [_fx("D", 0, 10), _fx("G", 5, 20), _fx("D", 7, 15), _fx("G", 12, 30)]
    bis = build_bis(fs, min_len=4)
    dirs = [b.direction for b in bis]
    assert len(dirs) >= 1
    assert all(dirs[i] != dirs[i + 1] for i in range(len(dirs) - 1))   # 严格交替
    assert bis[-1].end_fx.fx == 30.0                                   # 新高被保留为端点
