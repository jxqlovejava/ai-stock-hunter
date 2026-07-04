"""Layered SHA-256 hashing for determinism verification."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd

from oxq.core.types import Fill


def hash_mktdata(mktdata: dict[str, pd.DataFrame]) -> str:
    """Hash all mktdata DataFrames, symbol-order independent."""
    h = hashlib.sha256()
    for symbol in sorted(mktdata.keys()):
        h.update(symbol.encode())
        df = mktdata[symbol]
        h.update(pd.util.hash_pandas_object(df).values.tobytes())
    return f"sha256:{h.hexdigest()}"


def hash_trades(trades: list[Fill]) -> str:
    """Hash the trade list in order."""
    h = hashlib.sha256()
    for fill in trades:
        record = (
            fill.order.symbol,
            fill.order.side,
            fill.order.shares,
            fill.order.order_type,
            str(fill.filled_price),
            fill.filled_at,
            str(fill.fee),
        )
        h.update(json.dumps(record).encode())
    return f"sha256:{h.hexdigest()}"


def hash_equity(equity_curve: list[tuple[Any, float]]) -> str:
    """Hash the equity curve in order."""
    h = hashlib.sha256()
    for date, value in equity_curve:
        h.update(f"{date}:{value}".encode())
    return f"sha256:{h.hexdigest()}"


def combined_hash(
    mktdata_hash: str,
    trades_hash: str,
    equity_hash: str,
) -> str:
    """Combine three layer hashes into one result hash."""
    h = hashlib.sha256()
    h.update(mktdata_hash.encode())
    h.update(trades_hash.encode())
    h.update(equity_hash.encode())
    return f"sha256:{h.hexdigest()}"
