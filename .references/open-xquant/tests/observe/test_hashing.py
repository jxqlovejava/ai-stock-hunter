"""Tests for observe hashing -- layered SHA-256 for determinism verification."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from oxq.core.types import Fill, Order


class TestHashMktdata:
    def test_deterministic(self) -> None:
        from oxq.observe.hashing import hash_mktdata

        dates = pd.bdate_range("2024-01-01", periods=5)
        mktdata = {
            "AAPL": pd.DataFrame({"close": [150.0, 151.0, 152.0, 153.0, 154.0]}, index=dates),
        }
        h1 = hash_mktdata(mktdata)
        h2 = hash_mktdata(mktdata)
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_different_data_different_hash(self) -> None:
        from oxq.observe.hashing import hash_mktdata

        dates = pd.bdate_range("2024-01-01", periods=3)
        m1 = {"A": pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=dates)}
        m2 = {"A": pd.DataFrame({"close": [1.0, 2.0, 4.0]}, index=dates)}
        assert hash_mktdata(m1) != hash_mktdata(m2)

    def test_symbol_order_independent(self) -> None:
        from oxq.observe.hashing import hash_mktdata

        dates = pd.bdate_range("2024-01-01", periods=3)
        df_a = pd.DataFrame({"close": [1.0, 2.0, 3.0]}, index=dates)
        df_b = pd.DataFrame({"close": [4.0, 5.0, 6.0]}, index=dates)
        m1 = {"A": df_a, "B": df_b}
        m2 = {"B": df_b, "A": df_a}
        assert hash_mktdata(m1) == hash_mktdata(m2)

    def test_empty_mktdata(self) -> None:
        from oxq.observe.hashing import hash_mktdata

        h = hash_mktdata({})
        assert h.startswith("sha256:")


class TestHashTrades:
    def test_deterministic(self) -> None:
        from oxq.observe.hashing import hash_trades

        trades = [
            Fill(
                order=Order(symbol="AAPL", side="BUY", shares=100),
                filled_price=Decimal("150.00"),
                filled_at="2024-01-02",
            ),
        ]
        h1 = hash_trades(trades)
        h2 = hash_trades(trades)
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_empty_trades(self) -> None:
        from oxq.observe.hashing import hash_trades

        h = hash_trades([])
        assert h.startswith("sha256:")

    def test_different_trades_different_hash(self) -> None:
        from oxq.observe.hashing import hash_trades

        t1 = [Fill(order=Order(symbol="AAPL", side="BUY", shares=100),
                    filled_price=Decimal("150"), filled_at="2024-01-02")]
        t2 = [Fill(order=Order(symbol="AAPL", side="BUY", shares=200),
                    filled_price=Decimal("150"), filled_at="2024-01-02")]
        assert hash_trades(t1) != hash_trades(t2)


class TestHashEquity:
    def test_deterministic(self) -> None:
        from oxq.observe.hashing import hash_equity

        curve = [("2024-01-01", 100000.0), ("2024-01-02", 100500.0)]
        h1 = hash_equity(curve)
        h2 = hash_equity(curve)
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_empty_curve(self) -> None:
        from oxq.observe.hashing import hash_equity

        h = hash_equity([])
        assert h.startswith("sha256:")


class TestCombinedHash:
    def test_deterministic(self) -> None:
        from oxq.observe.hashing import combined_hash

        h = combined_hash("sha256:aaa", "sha256:bbb", "sha256:ccc")
        assert h.startswith("sha256:")
        assert combined_hash("sha256:aaa", "sha256:bbb", "sha256:ccc") == h

    def test_order_matters(self) -> None:
        from oxq.observe.hashing import combined_hash

        h1 = combined_hash("sha256:aaa", "sha256:bbb", "sha256:ccc")
        h2 = combined_hash("sha256:bbb", "sha256:aaa", "sha256:ccc")
        assert h1 != h2
