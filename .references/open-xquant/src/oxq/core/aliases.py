"""Indicator name aliases — Chinese ↔ English resolution."""

from __future__ import annotations

INDICATOR_ALIASES: dict[str, str] = {
    # Chinese → canonical English name
    "市净率": "pb",
    "市盈率": "pe_ttm",
    "动量": "momentum",
    "净资产收益率": "roe",
    "总资产收益率": "roa",
    "每股收益": "eps",
    "每股净资产": "book_value_per_share",
    "营业收入": "revenue",
    "净利润": "net_income",
    "市值": "market_cap",
    "波动率": "volatility",
    "换手率": "turnover_rate",
}

# Also allow English uppercase passthrough
_ENGLISH_CANONICAL: dict[str, str] = {
    "roe": "roe",
    "roa": "roa",
    "pe": "pe_ttm",
    "pe_ttm": "pe_ttm",
    "pb": "pb",
    "peg": "peg",
    "eps": "eps",
    "momentum": "momentum",
    "book_value_per_share": "book_value_per_share",
    "revenue": "revenue",
    "net_income": "net_income",
    "market_cap": "market_cap",
    "volatility": "volatility",
    "turnover_rate": "turnover_rate",
}


def resolve_alias(name: str) -> str:
    """Resolve a Chinese or English indicator name to its canonical form.

    Unknown names are returned as lowercase.
    """
    if name in INDICATOR_ALIASES:
        return INDICATOR_ALIASES[name]
    lower = name.lower()
    if lower in _ENGLISH_CANONICAL:
        return _ENGLISH_CANONICAL[lower]
    return lower
