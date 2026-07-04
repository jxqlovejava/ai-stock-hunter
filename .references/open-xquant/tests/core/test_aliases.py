"""Tests for indicator Chinese alias resolution."""

from oxq.core.aliases import resolve_alias


def test_resolve_chinese_alias() -> None:
    assert resolve_alias("市净率") == "pb"
    assert resolve_alias("市盈率") == "pe_ttm"
    assert resolve_alias("动量") == "momentum"
    assert resolve_alias("净资产收益率") == "roe"


def test_resolve_english_passthrough() -> None:
    """English names pass through unchanged."""
    assert resolve_alias("roe") == "roe"
    assert resolve_alias("pb") == "pb"
    assert resolve_alias("momentum") == "momentum"


def test_resolve_case_insensitive() -> None:
    assert resolve_alias("ROE") == "roe"
    assert resolve_alias("PB") == "pb"


def test_resolve_unknown_passthrough() -> None:
    """Unknown names pass through as lowercase."""
    assert resolve_alias("custom_factor") == "custom_factor"
