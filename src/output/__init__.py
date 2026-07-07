# -*- coding: utf-8 -*-
"""输出层: 盯盘 + 扫雷 + 报告生成。"""

from .alert import AlertManager
from .formatter import (
    format_analysis_result,
    format_nature_tag,
    format_citations_summary,
    format_diagnosis_panel,
    format_l2_verdict_detail,
)

__all__ = [
    "AlertManager",
    "format_analysis_result",
    "format_nature_tag",
    "format_citations_summary",
    "format_l1_score_panel",
    "format_l2_verdict_detail",
]
