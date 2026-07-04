"""Tests for expanded EastMoneyFetcher indicators (PE, PB, ROA, PEG)."""

from oxq.data.factors import EASTMONEY_FIELD_MAP, FINANCIAL_INDICATORS


def test_field_map_includes_new_indicators() -> None:
    """EASTMONEY_FIELD_MAP must include pe_ttm, pb, roa, peg."""
    assert "pe_ttm" in EASTMONEY_FIELD_MAP
    assert "pb" in EASTMONEY_FIELD_MAP
    assert "roa" in EASTMONEY_FIELD_MAP
    assert "peg" in EASTMONEY_FIELD_MAP


def test_financial_indicators_includes_new() -> None:
    """FINANCIAL_INDICATORS list must include new indicators."""
    assert "pe_ttm" in FINANCIAL_INDICATORS
    assert "pb" in FINANCIAL_INDICATORS
    assert "roa" in FINANCIAL_INDICATORS
    assert "peg" in FINANCIAL_INDICATORS


def test_eastmoney_fetcher_list_includes_new() -> None:
    """EastMoneyFetcher.list_indicators must include new indicators."""
    from oxq.data.factors import EastMoneyFetcher

    fetcher = EastMoneyFetcher()
    indicators = fetcher.list_indicators()
    assert "pe_ttm" in indicators
    assert "pb" in indicators
    assert "roa" in indicators
    assert "peg" in indicators
