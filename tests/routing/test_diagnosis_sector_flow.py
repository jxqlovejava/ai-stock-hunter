# -*- coding: utf-8 -*-
"""板块资金流向在 diagnosis 中的回归测试 — 行业匹配 / 排名 / 展示。"""
from __future__ import annotations

from types import SimpleNamespace

from src.routing.diagnosis import DiagnosisEngine


def _mk_sectors():
    names = [
        ("电子", 301.5e8, 1.5),
        ("有色金属", 135.8e8, 0.8),
        ("半导体", 129.6e8, 1.2),
        ("其他电子Ⅱ", 5.5e8, 0.3),
        ("银行", -50.0e8, -0.5),
    ]
    return [SimpleNamespace(sector_name=n, main_net=v, main_net_pct=p) for n, v, p in names]


_SNAP = SimpleNamespace(sectors=_mk_sectors())


class TestSectorFlowMatching:
    """行业归属匹配板块，不再恒为默认 50/50。"""

    def test_exact_industry_match(self):
        score, rank = DiagnosisEngine._compute_sector_flow_score(
            _SNAP, "沃尔核材", "其他电子Ⅱ"
        )
        assert score != 50.0 or rank != 50  # 命中具体板块
        assert 0.0 <= score <= 100.0 and 0 <= rank <= 100

    def test_fuzzy_industry_match(self):
        # 行业名包含在板块名中 → 模糊命中
        m = DiagnosisEngine._match_sector(_SNAP, "沃尔核材", "电子")
        assert m is not None
        assert "电子" in m.sector_name

    def test_stock_name_fallback_when_no_industry(self):
        # 无行业 → 用股票名包含板块名兜底（银行股）
        m = DiagnosisEngine._match_sector(_SNAP, "招商银行", "")
        assert m is not None and m.sector_name == "银行"

    def test_no_match_returns_default(self):
        score, rank = DiagnosisEngine._compute_sector_flow_score(
            _SNAP, "无关名称", ""
        )
        assert score == 50.0 and rank == 50

    def test_no_sectors_returns_default(self):
        empty = SimpleNamespace(sectors=[])
        assert DiagnosisEngine._compute_sector_flow_score(empty, "X", "") == (50.0, 50)

    def test_top_rank_sector_scores_high(self):
        # 净流入最大的板块应得高排名
        score, rank = DiagnosisEngine._compute_sector_flow_score(
            _SNAP, "电子龙头", "电子"
        )
        assert rank >= 60  # 净流入第一板块排名靠前

    def test_rank_percentile_direction(self):
        # 净流入最大板块 → 百分位高分（>=80）且序数 idx=1。
        # 锁定「rank 大 = 流入强」语义，保证动量微调方向（>=80 → +5%）正确。
        score, rank, idx = DiagnosisEngine._rank_of(_SNAP, _SNAP.sectors[0])
        assert idx == 1
        assert rank >= 80


class TestSectorFlowRendering:
    """diagnose CLI / Markdown 报告展示板块资金详情。"""

    @staticmethod
    def _report():
        return SimpleNamespace(
            sector_flow_score=86.0,
            sector_flow_rank=86,
            sector_flow_detail={
                "sector_name": "其他电子Ⅱ",
                "main_net": 5.5e8,
                "main_net_pct": 0.3,
                "rank": 4,  # 序数：1=净流入最大
                "total_sectors": 5,
            },
            sector_flow_top=[
                {"sector_name": "电子", "main_net": 301.5e8},
                {"sector_name": "有色金属", "main_net": 135.8e8},
            ],
            sentiment_signal="NORMAL",
            data_freshness=None,
        )

    def test_print_diagnosis_shows_sector_detail(self, capsys):
        from src.output.step_output import print_diagnosis

        print_diagnosis(self._report())
        out = capsys.readouterr().out
        assert "所属板块" in out
        assert "其他电子Ⅱ" in out
        assert "当日净流入Top" in out
        assert "电子" in out

    def test_markdown_report_includes_sector_flow(self):
        from src.output.markdown_report import _build_report

        result = SimpleNamespace(
            name="沃尔核材", symbol="002130", report=self._report(),
        )
        md = "\n".join(_build_report(result))
        assert "所属板块" in md
        assert "当日净流入Top" in md
