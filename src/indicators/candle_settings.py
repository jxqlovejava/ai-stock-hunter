# -*- coding: utf-8 -*-
"""Predefined CandleSettings constants for candlestick pattern recognition.

Each setting overrides specific thresholds of the default CandleSettings.
Usage:

    from src.indicators.candle_settings import SHORT_BODY, LONG_SHADOW
    from src.indicators.base import CandleSettings

    my_settings = CandleSettings(**SHORT_BODY, **LONG_SHADOW)
"""

from __future__ import annotations

from .base import CandleSettings

# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

_DEFAULT = CandleSettings()

# ---------------------------------------------------------------------------
# Body-length presets
# ---------------------------------------------------------------------------

SHORT_BODY: dict = {
    "body_short": 0.10,
    "body_long": 0.15,
}
"""Aggressive short-body detection — candles with body < 15% range are
treated as already-long for "long body" checks."""

LONG_BODY: dict = {
    "body_short": 0.15,
    "body_long": 0.40,
}
"""Conservative long-body — body must exceed 40% of range."""

TINY_BODY: dict = {
    "body_short": 0.05,
    "body_long": 0.30,
}
"""Very strict doji detection."""

FULL_BODY: dict = {
    "body_short": 0.30,
    "body_long": 0.80,
}
"""Marubozu-style — only extremely long bodies count as "long"."""

# ---------------------------------------------------------------------------
# Shadow presets
# ---------------------------------------------------------------------------

SHORT_SHADOW: dict = {
    "shadow_short": 0.10,
    "shadow_long": 0.20,
}
"""Any shadow > 20% of range is already "long"."""

LONG_SHADOW: dict = {
    "shadow_short": 0.15,
    "shadow_long": 0.40,
}
"""Shadow must exceed 40% of range to be noteworthy."""

NONEXISTENT_SHADOW: dict = {
    "shadow_short": 0.03,
    "shadow_long": 0.10,
}
"""Only extreme shadows register — used for Marubozu detection."""

# ---------------------------------------------------------------------------
# Proximity presets
# ---------------------------------------------------------------------------

NEAR: dict = {
    "near": 0.05,
    "far": 0.20,
}
"""Tight proximity — used for Harami, Piercing, DarkCloudCover."""

FAR: dict = {
    "near": 0.15,
    "far": 0.40,
}
"""Loose proximity — used for breakaway gaps."""

TOLERANT: dict = {
    "near": 0.03,
    "far": 0.10,
    "equality": 0.003,
}
"""Very strict comparisons — used for Doji detection."""

# ---------------------------------------------------------------------------
# Combined convenience settings
# ---------------------------------------------------------------------------

DOJI_SETTINGS: dict = {
    **_DEFAULT.__dict__,
    **TINY_BODY,
    **SHORT_SHADOW,
    **TOLERANT,
}
"""Settings tuned for accurate Doji-family detection."""

MARUBOZU_SETTINGS: dict = {
    **_DEFAULT.__dict__,
    **FULL_BODY,
    **NONEXISTENT_SHADOW,
}
"""Settings tuned for Marubozu detection (near-full body, no shadows)."""

HAMMER_SETTINGS: dict = {
    **_DEFAULT.__dict__,
    **SHORT_BODY,
    **LONG_SHADOW,
}
"""Settings tuned for Hammer / HangingMan detection."""
