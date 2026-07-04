"""Tests for signals._ops.resolve_op — alias resolution and error handling."""

import operator

import pytest

from oxq.signals._ops import resolve_op


class TestCanonicalValues:
    """Canonical names (gt, lt, gte, lte, eq, ne) must resolve to the correct operator."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("gt", operator.gt),
            ("lt", operator.lt),
            ("gte", operator.ge),
            ("lte", operator.le),
            ("eq", operator.eq),
            ("ne", operator.ne),
        ],
    )
    def test_canonical(self, name: str, expected):
        assert resolve_op(name) is expected


class TestSymbolAliases:
    """Common symbolic aliases must map to the right operator."""

    @pytest.mark.parametrize(
        ("alias", "expected"),
        [
            (">", operator.gt),
            ("<", operator.lt),
            (">=", operator.ge),
            ("<=", operator.le),
            ("==", operator.eq),
            ("!=", operator.ne),
            ("<>", operator.ne),
            ("=", operator.eq),
        ],
    )
    def test_symbol_alias(self, alias: str, expected):
        assert resolve_op(alias) is expected


class TestWordAliases:
    """English word aliases must map to the right operator."""

    @pytest.mark.parametrize(
        ("alias", "expected"),
        [
            ("above", operator.gt),
            ("below", operator.lt),
        ],
    )
    def test_word_alias(self, alias: str, expected):
        assert resolve_op(alias) is expected


class TestStripping:
    """Leading/trailing whitespace must be tolerated."""

    def test_strip_spaces(self):
        assert resolve_op("  gt  ") is operator.gt

    def test_strip_alias(self):
        assert resolve_op(" > ") is operator.gt


class TestInvalidInput:
    """Unknown values must raise ValueError with a helpful message."""

    def test_unknown_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown relationship"):
            resolve_op("greater_than")

    def test_error_lists_valid_options(self):
        with pytest.raises(ValueError, match="gt"):
            resolve_op("oops")

    def test_empty_string(self):
        with pytest.raises(ValueError):
            resolve_op("")
