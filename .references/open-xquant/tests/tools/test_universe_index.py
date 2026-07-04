"""Tests for universe_set(type='index'), universe_list_indexes(), and filter audit table."""

from unittest.mock import patch

import pandas as pd

from oxq.tools.universe import universe_list_indexes, universe_set
from oxq.universe.index import INDEX_REGISTRY


def _patch_fetch(key: str, return_value: list[str]):
    """Patch the fetch_fn stored in INDEX_REGISTRY for a given key."""
    return patch.dict(
        INDEX_REGISTRY, {key: {**INDEX_REGISTRY[key], "fetch_fn": lambda code: return_value}}
    )


def test_universe_list_indexes_returns_builtin() -> None:
    """universe_list_indexes must return real indexes, not empty."""
    result = universe_list_indexes()
    assert len(result["indexes"]) >= 4
    keys = [idx["key"] for idx in result["indexes"]]
    assert "csi300" in keys
    assert "sse50" in keys
    # Phase 2 note should be gone
    assert "note" not in result or "Phase 2" not in result.get("note", "")


def test_universe_set_type_index() -> None:
    """universe_set(type='index') returns constituent symbols."""

    fake_symbols = ["600519", "000858", "000001"]

    with _patch_fetch("csi300", fake_symbols):
        result = universe_set(type="index", code="csi300")

    assert result["symbols"] == fake_symbols
    assert result["count"] == 3
    assert "csi300" in result["source"]


def test_universe_set_type_index_unknown_code() -> None:
    """universe_set(type='index') with unknown code returns error."""
    result = universe_set(type="index", code="nonexistent")
    assert "error" in result


def test_universe_set_type_index_uses_code_param() -> None:
    """universe_set uses the code parameter to select index."""

    with _patch_fetch("sse50", ["000001"]):
        result = universe_set(type="index", code="sse50")

    assert result["count"] == 1
    assert "sse50" in result["source"]


def test_universe_set_filter_returns_details() -> None:
    """universe_set(type='filter') must include details audit table."""
    from pathlib import Path

    dates = pd.date_range("2026-04-10", periods=3, freq="B")

    mktdata_600519 = pd.DataFrame(
        {"close": [1800, 1810, 1820], "volume": [50000, 51000, 52000],
         "roe": [30.0, 30.1, 30.2], "pb": [8.0, 8.1, 8.2]},
        index=dates,
    )
    mktdata_000858 = pd.DataFrame(
        {"close": [200, 201, 202], "volume": [80000, 81000, 82000],
         "roe": [12.0, 12.1, 12.2], "pb": [5.0, 5.1, 5.2]},
        index=dates,
    )

    with patch("oxq.tools.universe.resolve_data_dir") as mock_resolve, \
         patch("pandas.read_parquet") as mock_read:

        mock_resolve.return_value = Path("/fake/data")

        with patch("pathlib.Path.exists", return_value=True):
            mock_read.side_effect = [mktdata_600519, mktdata_000858]
            result = universe_set(
                type="filter",
                symbols=["600519", "000858"],
                filters=[
                    {"column": "roe", "op": ">", "value": 15},
                    {"column": "pb", "op": "<", "value": 10},
                ],
                as_of_date="2026-04-14",
            )

    assert result["symbols"] == ["600519"]  # 000858 roe=12.2 < 15
    assert "details" in result
    assert len(result["details"]) == 2  # both symbols shown
    # Check detail entries have factor values
    detail_600519 = next(d for d in result["details"] if d["symbol"] == "600519")
    assert detail_600519["pass"] is True
    assert detail_600519["roe"] == 30.2
    detail_000858 = next(d for d in result["details"] if d["symbol"] == "000858")
    assert detail_000858["pass"] is False
