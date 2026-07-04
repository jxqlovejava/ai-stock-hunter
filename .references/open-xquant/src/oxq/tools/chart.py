"""Chart tools — visualize market data and indicators."""

from __future__ import annotations

import tempfile
from typing import Any

from oxq.tools import session
from oxq.tools.registry import registry


@registry.tool(
    name="chart_indicator",
    description=(
        "Render a candlestick chart with indicator overlays or subplots for a "
        "given run result. Returns the file path of the saved PNG image."
    ),
)
def chart_indicator(
    run_id: str,
    symbol: str,
    columns: list[str],
    overlay: bool = True,
) -> dict[str, Any]:
    """Plot price chart with indicator columns from a run result.

    Parameters
    ----------
    run_id : str
        Key in ``session._run_results``.
    symbol : str
        Which symbol to plot.
    columns : list[str]
        Indicator column names to plot (must exist in the symbol's DataFrame).
    overlay : bool
        If True, draw indicators on the price panel.
        If False, draw indicators in a separate subplot below volume.
    """
    try:
        import mplfinance as mpf
    except ImportError:
        return {
            "error": (
                "mplfinance is not installed. "
                "Install it with: pip install 'open-xquant[chart]'"
            ),
        }

    result = session._run_results.get(run_id)
    if result is None:
        return {"error": f"Run '{run_id}' not found"}

    if symbol not in result.mktdata:
        available = sorted(result.mktdata.keys())
        return {"error": f"Symbol '{symbol}' not in run data. Available: {available}"}

    df = result.mktdata[symbol]

    missing = [c for c in columns if c not in df.columns]
    if missing:
        available = sorted(set(df.columns) - {"open", "high", "low", "close", "volume"})
        return {"error": f"Columns not found: {missing}. Available indicators: {available}"}

    # Build addplot list
    addplots = []
    for col in columns:
        addplots.append(
            mpf.make_addplot(
                df[col],
                panel=0 if overlay else 2,
                secondary_y=False,
                label=col,
            )
        )

    # Save to temp file
    tmp = tempfile.NamedTemporaryFile(suffix=".png", prefix="oxq_chart_", delete=False)
    tmp.close()

    mpf.plot(
        df,
        type="candle",
        volume=True,
        addplot=addplots if addplots else None,
        title=f"{symbol}",
        savefig=tmp.name,
        style="charles",
        figsize=(14, 8),
    )

    return {
        "path": tmp.name,
        "symbol": symbol,
        "columns": columns,
        "overlay": overlay,
        "rows": len(df),
    }
