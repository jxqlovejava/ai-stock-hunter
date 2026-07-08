# -*- coding: utf-8 -*-
"""Confidence Gate — 在信号进入 仓位调度阶段前校验数据可信度。"""

from __future__ import annotations

from src.data.source_citation import (
    NATURE_DATA_GAP,
    NATURE_SPECULATION,
    SourceCitation,
    UNSOURCED_CITATION,
)


class ConfidenceTooLowError(Exception):
    """Confidence 低于阈值时抛出。"""


class ConfidenceGate:
    """校验 citation 是否满足进入仓位调度的最低要求。"""

    MIN_CONFIDENCE = 0.6

    @classmethod
    def check(cls, citation: SourceCitation | None, context: str = "") -> SourceCitation:
        """检查 citation，返回原对象；不满足时抛出异常并附原因。"""
        if citation is None:
            raise ConfidenceTooLowError(
                f"{context}: 缺少 SourceCitation，标记 [UNSOURCED]"
            )

        if citation.nature == NATURE_DATA_GAP:
            raise ConfidenceTooLowError(
                f"{context}: [DATA_GAP] {citation.provider}/{citation.field}"
            )

        if citation.provider == UNSOURCED_CITATION.provider:
            raise ConfidenceTooLowError(
                f"{context}: [UNSOURCED] {citation.field}"
            )

        effective_confidence = citation.quality_score
        if effective_confidence < cls.MIN_CONFIDENCE:
            raise ConfidenceTooLowError(
                f"{context}: confidence {effective_confidence:.2f} < {cls.MIN_CONFIDENCE}"
            )

        return citation

    @classmethod
    def check_many(
        cls, citations: list[SourceCitation], context: str = ""
    ) -> SourceCitation:
        """检查多个 citation，返回最低 confidence 的那个；任一失败即抛异常。"""
        if not citations:
            raise ConfidenceTooLowError(f"{context}: citation 列表为空")
        for c in citations:
            cls.check(c, context)
        return min(citations, key=lambda x: x.quality_score)
