# -*- coding: utf-8 -*-
"""反操纵渲染接线 — 资金背离单一形状 + 进度条辅助函数。

覆盖:
  ① _score_bar 越界安全（0/100 边界、负数/超限钳制）
  ② print_manipulation_info 资金背离裸 float 渲染（含 turnover 缺失置零的 0.0）
  ③ dict 形状已被归一为 float，不再产生死分支
"""
from __future__ import annotations

from src.output.step_output import _score_bar, print_manipulation_info


class TestScoreBar:
    """_score_bar 进度条辅助函数。"""

    def test_zero_is_empty_bar(self):
        assert _score_bar(0.0) == "░" * 10

    def test_full_mark_all_filled(self):
        assert _score_bar(100.0) == "█" * 10

    def test_mid_score_rounds_to_tens(self):
        assert _score_bar(55.0) == "█" * 5 + "░" * 5
        assert _score_bar(60.0) == "█" * 6 + "░" * 4

    def test_out_of_range_is_clamped(self):
        assert _score_bar(150.0) == "█" * 10   # 超限不溢出
        assert _score_bar(-5.0) == "░" * 10    # 负数不产生负格


class TestManipulationDivergenceRender:
    """print_manipulation_info 资金背离行（orchestrator 存裸 float）。"""

    def test_float_divergence_renders(self, capsys):
        print_manipulation_info({"capital_divergence": 55.0})
        out = capsys.readouterr().out
        assert "反操纵深扫" in out
        assert "资金背离" in out
        assert "55/100" in out

    def test_zero_divergence_renders_not_silenced(self, capsys):
        """turnover 缺失 → divergence_score=0.0，仍须渲染，反操纵块不得成空壳。"""
        print_manipulation_info({"capital_divergence": 0.0})
        out = capsys.readouterr().out
        assert "资金背离" in out
        assert "0/100" in out

    def test_dict_shape_no_longer_renders_or_crashes(self, capsys):
        """dict 形状已被归一为 float — 不渲染也不报错（无生产者产出该形状）。"""
        print_manipulation_info({"capital_divergence": {"score": 55, "type": "bull_trap"}})
        out = capsys.readouterr().out
        assert "资金背离" not in out

    def test_missing_key_is_quiet(self, capsys):
        """capital_divergence 缺失（无该键）→ 不渲染该行。"""
        print_manipulation_info({"chip_risk": 40.0})
        out = capsys.readouterr().out
        assert "资金背离" not in out
