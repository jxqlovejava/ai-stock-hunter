# tests/indicators/test_chanlun_schema.py
# -*- coding: utf-8 -*-
from src.indicators.chanlun.schema import Bi, ChanlunPoint, ChanlunResult, Fractal, ZhongShu


def test_fractal_fields():
    f = Fractal(mark="G", dt="2026-01-05", high=12.0, low=10.0, fx=12.0, index=4)
    assert f.mark == "G" and f.fx == 12.0 and f.index == 4


def test_result_to_summary_dict():
    zs = ZhongShu(zg=18.0, zd=15.0, zz=16.5, gg=20.0, dd=12.0,
                  start_dt="2026-01-01", end_dt="2026-01-10", state="形成")
    p = ChanlunPoint(kind="一买", dt="2026-02-01", price=15.0, confidence=0.7,
                     rationale="下降末段底背驰")
    r = ChanlunResult(symbol="000001", name="测试", freq="D", backend="self",
                      fractals=[], bis=[], zhongshus=[zs], points=[p],
                      current_state={"position": "中枢内"}, signals={"entry": [], "exit": []},
                      source_citations=[], confidence=0.8)
    d = r.to_summary_dict()
    assert d["backend"] == "self"
    assert d["zhongshu_count"] == 1
    assert d["last_zs"]["zg"] == 18.0
    assert d["points"][0]["kind"] == "一买"
    assert d["signals"] == {"entry": [], "exit": []}
