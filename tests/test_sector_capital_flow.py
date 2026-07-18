# -*- coding: utf-8 -*-
"""板块资金流向功能单元测试。"""

from __future__ import annotations

import pandas as pd
import pytest

from src.data.aggregator import DataAggregator
from src.data.schema import SectorCapitalFlowItem, SectorCapitalFlowSnapshot
from src.industry.daily_ranking import format_sector_flow_table
from src.routing.diagnosis import DiagnosisEngine


def test_build_sector_flow_snapshot():
    df = pd.DataFrame({
        "名称": ["电子", "银行", "食品饮料"],
        "今日涨跌幅": [1.2, -0.5, 0.8],
        "今日主力净流入-净额": [123456.0, -45678.0, 78901.0],
        "今日主力净流入-净占比": [5.4, -2.1, 3.2],
        "今日超大单净流入-净额": [100000.0, -30000.0, 50000.0],
        "今日超大单净流入-净占比": [4.0, -1.5, 2.0],
        "今日大单净流入-净额": [23456.0, -15678.0, 28901.0],
        "今日大单净流入-净占比": [1.4, -0.6, 1.2],
        "今日中单净流入-净额": [10000.0, -2000.0, -5000.0],
        "今日中单净流入-净占比": [0.5, -0.1, -0.3],
        "今日小单净流入-净额": [-5000.0, 1000.0, -3000.0],
        "今日小单净流入-净占比": [-0.2, 0.1, -0.1],
        "今日主力净流入最大股": ["A", "C", "B"],
        "序号": [1, 3, 2],
    })
    snapshot = DataAggregator._build_sector_flow_snapshot(df, "今日")
    assert len(snapshot.sectors) == 3
    electronic = next(s for s in snapshot.sectors if s.sector_name == "电子")
    assert electronic.main_net == 123456.0
    assert electronic.main_net_pct == 5.4


def test_build_sector_flow_snapshot_empty():
    snapshot = DataAggregator._build_sector_flow_snapshot(pd.DataFrame(), "今日")
    assert snapshot.sectors == []


def test_format_sector_flow_table():
    df = pd.DataFrame({
        "名称": ["电子", "计算机", "银行"],
        "今日主力净流入-净额": [123456.0, 45678.0, -56789.0],
    })
    text = format_sector_flow_table(df, top_n=2)
    assert "净流入 Top 2" in text
    assert "净流出 Top 2" in text
    assert "电子(+12.3亿)" in text
    assert "银行(-5.7亿)" in text


def test_format_sector_flow_table_empty():
    assert "[DATA_GAP]" in format_sector_flow_table(pd.DataFrame())


def test_compute_sector_flow_score():
    flow = SectorCapitalFlowSnapshot(indicator="今日", sectors=[
        SectorCapitalFlowItem(sector_name="电子", main_net=100000),
        SectorCapitalFlowItem(sector_name="食品饮料", main_net=20000),
        SectorCapitalFlowItem(sector_name="银行", main_net=-50000),
    ])
    score, rank = DiagnosisEngine._compute_sector_flow_score(flow, "电子科技")
    assert score == 100.0
    assert rank == 100

    score, rank = DiagnosisEngine._compute_sector_flow_score(flow, "银行股份")
    assert score == 0.0
    assert rank == 0


def test_compute_sector_flow_score_no_match():
    flow = SectorCapitalFlowSnapshot(indicator="今日", sectors=[
        SectorCapitalFlowItem(sector_name="电子", main_net=100000),
    ])
    score, rank = DiagnosisEngine._compute_sector_flow_score(flow, "未知行业")
    assert score == 50.0
    assert rank == 50


def test_compute_sector_flow_score_empty():
    flow = SectorCapitalFlowSnapshot(indicator="今日")
    score, rank = DiagnosisEngine._compute_sector_flow_score(flow, "电子")
    assert score == 50.0
    assert rank == 50
