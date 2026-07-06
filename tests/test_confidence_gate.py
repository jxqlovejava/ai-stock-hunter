# -*- coding: utf-8 -*-
"""ConfidenceGate 单元测试。"""

from __future__ import annotations

import pytest

from src.data.source_citation import (
    NATURE_DATA_GAP,
    NATURE_SPECULATION,
    SourceCitation,
    make_citation,
    make_data_gap_citation,
)
from src.pipeline.confidence_gate import ConfidenceGate, ConfidenceTooLowError


def test_passes_for_high_confidence():
    c = make_citation(provider="guosen", field="close")
    assert ConfidenceGate.check(c).provider == "guosen"


def test_blocks_low_confidence():
    c = SourceCitation(
        provider="llm_derived",
        field="close",
        confidence=0.4,
        nature="speculation",
        source_tier="T3",
    )
    with pytest.raises(ConfidenceTooLowError):
        ConfidenceGate.check(c)


def test_blocks_data_gap():
    c = make_data_gap_citation("akshare", "close")
    with pytest.raises(ConfidenceTooLowError) as exc:
        ConfidenceGate.check(c)
    assert "[DATA_GAP]" in str(exc.value)


def test_blocks_unsourced():
    c = SourceCitation(
        provider="unsourced",
        field="unknown",
        confidence=0.0,
        nature=NATURE_SPECULATION,
        source_tier="T3",
    )
    with pytest.raises(ConfidenceTooLowError) as exc:
        ConfidenceGate.check(c)
    assert "[UNSOURCED]" in str(exc.value)


def test_blocks_missing_citation():
    with pytest.raises(ConfidenceTooLowError):
        ConfidenceGate.check(None)


def test_check_many_returns_weakest():
    c1 = make_citation(provider="guosen", field="close")
    c2 = make_citation(provider="akshare", field="close")
    weakest = ConfidenceGate.check_many([c1, c2])
    assert weakest.provider == "akshare"
