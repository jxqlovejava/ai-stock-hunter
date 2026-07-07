# -*- coding: utf-8 -*-
"""输出层: 盯盘 + 扫雷 + 报告生成。"""

from .alert import AlertManager
from .formatter import format_analysis_result

__all__ = ["AlertManager", "format_analysis_result"]
