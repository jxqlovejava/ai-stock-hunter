"""Tests for IndexUniverse — index constituent resolution."""

import pytest

from oxq.universe.base import UniverseProvider, UniverseSnapshot
from oxq.universe.index import (
    INDEX_REGISTRY,
    IndexUniverse,
    list_indexes,
    register_index,
)


def test_index_universe_satisfies_protocol() -> None:
    """IndexUniverse must satisfy UniverseProvider protocol."""

    def fake_fetch(code: str) -> list[str]:
        return ["600519", "000858"]

    universe: UniverseProvider = IndexUniverse(
        key="test_idx", fetch_fn=fake_fetch,
    )
    assert isinstance(universe, UniverseProvider)


def test_index_universe_get_universe() -> None:
    """get_universe returns snapshot with symbols from fetch_fn."""

    def fake_fetch(code: str) -> list[str]:
        return ["600519", "000858", "000001"]

    universe = IndexUniverse(key="csi300", fetch_fn=fake_fetch)
    snapshot = universe.get_universe("2026-04-14")

    assert snapshot.as_of_date == "2026-04-14"
    assert snapshot.symbols == ("600519", "000858", "000001")
    assert "csi300" in snapshot.source
    assert snapshot.metadata["index_key"] == "csi300"
    assert snapshot.metadata["count"] == 3


def test_index_universe_get_history() -> None:
    """get_history returns snapshots for start and end dates."""

    def fake_fetch(code: str) -> list[str]:
        return ["600519"]

    universe = IndexUniverse(key="csi300", fetch_fn=fake_fetch)
    history = universe.get_history("2026-01-01", "2026-04-14")

    assert len(history) == 2
    assert history[0].as_of_date == "2026-01-01"
    assert history[1].as_of_date == "2026-04-14"


def test_builtin_indexes_registered() -> None:
    """Day-1 indexes (csi300, csi500, csi1000, sse50) must be in registry."""
    assert "csi300" in INDEX_REGISTRY
    assert "csi500" in INDEX_REGISTRY
    assert "csi1000" in INDEX_REGISTRY
    assert "sse50" in INDEX_REGISTRY


def test_list_indexes_returns_all() -> None:
    """list_indexes returns info for all registered indexes."""
    indexes = list_indexes()
    keys = [idx["key"] for idx in indexes]
    assert "csi300" in keys
    assert "csi500" in keys


def test_register_custom_index() -> None:
    """Users can register custom indexes."""

    def my_fetch(code: str) -> list[str]:
        return ["AAPL", "GOOG"]

    register_index(key="my_index", code="CUSTOM", name="My Index", fetch_fn=my_fetch)
    assert "my_index" in INDEX_REGISTRY

    universe = IndexUniverse(key="my_index")
    snapshot = universe.get_universe("2026-04-14")
    assert snapshot.symbols == ("AAPL", "GOOG")

    # Clean up
    del INDEX_REGISTRY["my_index"]


def test_index_universe_unknown_key_raises() -> None:
    """IndexUniverse with unknown key and no fetch_fn raises ValueError."""
    with pytest.raises(ValueError, match="Unknown index"):
        IndexUniverse(key="nonexistent")
