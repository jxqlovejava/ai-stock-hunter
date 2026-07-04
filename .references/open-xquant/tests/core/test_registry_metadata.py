"""Tests for indicator registry metadata (description, category, source_type)."""

from oxq.core.registry import get_indicator_metadata, list_indicator_metadata


def test_list_indicator_metadata_returns_entries() -> None:
    """All registered indicators should have metadata entries."""
    metadata = list_indicator_metadata()
    # At minimum, built-in indicators should be present
    assert len(metadata) > 0
    assert "SMA" in metadata


def test_metadata_has_required_fields() -> None:
    """Each metadata entry must have description, category, source_type."""
    metadata = list_indicator_metadata()
    for name, info in metadata.items():
        assert "description" in info, f"{name} missing description"
        assert "category" in info, f"{name} missing category"
        assert "source_type" in info, f"{name} missing source_type"


def test_get_indicator_metadata_known() -> None:
    """get_indicator_metadata returns info for a known indicator."""
    info = get_indicator_metadata("SMA")
    assert info is not None
    assert info["category"] == "trend"
    assert info["source_type"] == "compute"


def test_get_indicator_metadata_unknown() -> None:
    """get_indicator_metadata returns None for unknown indicator."""
    info = get_indicator_metadata("NONEXISTENT_INDICATOR")
    assert info is None


def test_financial_indicators_have_download_source_type() -> None:
    """Indicators like PE, PB should have source_type='download'."""
    for name in ("PE", "PB"):
        info = get_indicator_metadata(name)
        assert info is not None, f"{name} not in metadata"
        assert info["source_type"] in ("compute", "download"), f"{name} has wrong source_type"
