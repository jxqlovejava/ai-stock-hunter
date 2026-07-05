"""Backtest visualization — equity curves, drawdowns, heatmaps, factor attribution.

Generates PNG charts via matplotlib and HTML summary reports.
Falls back to ASCII text output if matplotlib is unavailable.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path("backtest_results")


class BacktestVisualizer:
    """Chart generator for backtest results.

    Input: BacktestResult dataclass + optional trade log.
    Output: PNG charts + HTML summary report.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self._output_dir = output_dir or DEFAULT_OUTPUT_DIR
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._has_matplotlib = self._check_matplotlib()

    @staticmethod
    def _check_matplotlib() -> bool:
        try:
            import matplotlib  # noqa: F401
            return True
        except ImportError:
            logger.warning("matplotlib not installed — using ASCII fallback")
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def equity_curve(
        self,
        equity: list[float],
        dates: Optional[list[str]] = None,
        benchmark: Optional[list[float]] = None,
        title: str = "Equity Curve",
    ) -> str:
        """Generate equity curve chart. Returns file path."""
        if not self._has_matplotlib:
            return self._equity_curve_ascii(equity, dates)

        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8),
                                        gridspec_kw={"height_ratios": [3, 1]})

        # Parse dates or use index
        if dates:
            x = [datetime.strptime(d, "%Y-%m-%d") for d in dates]
        else:
            x = list(range(len(equity)))

        # Equity curve
        ax1.plot(x, equity, color="#2196F3", linewidth=1.5, label="Strategy")
        if benchmark:
            ax1.plot(x, benchmark, color="#9E9E9E", linewidth=1,
                     linestyle="--", label="Benchmark")
        ax1.fill_between(x, 1.0, equity, alpha=0.1, color="#2196F3")
        ax1.axhline(y=1.0, color="black", linewidth=0.5, linestyle=":")
        ax1.set_title(title, fontsize=14, fontweight="bold")
        ax1.set_ylabel("Net Value")
        ax1.legend(loc="upper left")
        ax1.grid(True, alpha=0.3)

        if dates:
            ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
            plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha="right")

        # Drawdown subplot
        peak = 1.0
        drawdowns = []
        for v in equity:
            peak = max(peak, v)
            dd = (v - peak) / peak * 100
            drawdowns.append(dd)

        ax2.fill_between(x, drawdowns, 0, color="#F44336", alpha=0.3)
        ax2.plot(x, drawdowns, color="#F44336", linewidth=1)
        ax2.set_ylabel("Drawdown %")
        ax2.set_xlabel("Date")
        ax2.grid(True, alpha=0.3)

        if dates:
            ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
            plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha="right")

        plt.tight_layout()
        path = self._output_dir / "equity_curve.png"
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
        return str(path)

    def drawdown_chart(self, equity: list[float], dates: Optional[list[str]] = None) -> str:
        """Generate standalone drawdown analysis chart."""
        if not self._has_matplotlib:
            return self._drawdown_ascii(equity)

        import matplotlib.pyplot as plt
        from datetime import datetime

        peak = 1.0
        max_dd = 0.0
        max_dd_start = 0
        max_dd_end = 0
        current_dd_start = 0
        drawdowns = []

        for i, v in enumerate(equity):
            if v >= peak:
                peak = v
                current_dd_start = i
            dd = (v - peak) / peak * 100
            drawdowns.append(dd)
            if dd < max_dd:
                max_dd = dd
                max_dd_start = current_dd_start
                max_dd_end = i

        if dates:
            x = [datetime.strptime(d, "%Y-%m-%d") for d in dates]
        else:
            x = list(range(len(equity)))

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.fill_between(x, drawdowns, 0, color="#F44336", alpha=0.3)
        ax.plot(x, drawdowns, color="#F44336", linewidth=1.5)

        # Highlight max drawdown
        if max_dd < 0 and max_dd_start < max_dd_end:
            ax.axvspan(x[max_dd_start], x[max_dd_end], alpha=0.15, color="red",
                       label=f"Max DD: {abs(max_dd):.1f}%")

        ax.set_title("Drawdown Analysis", fontsize=14, fontweight="bold")
        ax.set_ylabel("Drawdown %")
        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        path = self._output_dir / "drawdown.png"
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
        return str(path)

    def yearly_heatmap(self, monthly_returns: dict[str, float]) -> str:
        """Generate calendar heatmap of monthly returns. {YYYY-MM: return_pct}."""
        if not self._has_matplotlib:
            return self._heatmap_ascii(monthly_returns)

        import matplotlib.pyplot as plt
        import numpy as np

        # Parse into years × months matrix
        years = sorted(set(k[:4] for k in monthly_returns))
        months = [f"{m:02d}" for m in range(1, 13)]
        data = np.full((len(years), 12), np.nan)
        for k, v in monthly_returns.items():
            y = k[:4]
            m = k[5:7]
            if y in years and m in months:
                data[years.index(y), months.index(m)] = v

        fig, ax = plt.subplots(figsize=(14, len(years) * 0.6 + 2))
        cmap = plt.cm.RdYlGn
        im = ax.imshow(data, cmap=cmap, aspect="auto", vmin=-15, vmax=15)

        # Annotate
        for i in range(len(years)):
            for j in range(12):
                val = data[i, j]
                if not np.isnan(val):
                    color = "white" if abs(val) > 8 else "black"
                    ax.text(j, i, f"{val:.1f}", ha="center", va="center",
                            fontsize=8, color=color)

        ax.set_xticks(range(12))
        ax.set_xticklabels(["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"])
        ax.set_yticks(range(len(years)))
        ax.set_yticklabels(years)
        ax.set_title("Monthly Returns Heatmap (%)", fontsize=14, fontweight="bold")

        plt.colorbar(im, ax=ax, shrink=0.8)
        plt.tight_layout()
        path = self._output_dir / "monthly_heatmap.png"
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
        return str(path)

    def factor_attribution(
        self,
        factor_names: list[str],
        factor_returns: list[float],
        title: str = "Factor Attribution",
    ) -> str:
        """Generate factor return attribution bar chart."""
        if not self._has_matplotlib:
            return self._attribution_ascii(factor_names, factor_returns)

        import matplotlib.pyplot as plt

        colors = ["#4CAF50" if r >= 0 else "#F44336" for r in factor_returns]

        fig, ax = plt.subplots(figsize=(10, 6))
        bars = ax.barh(factor_names, factor_returns, color=colors, alpha=0.8,
                       edgecolor="white", linewidth=0.5)
        ax.axvline(x=0, color="black", linewidth=0.5)
        ax.set_xlabel("Return Contribution (%)")
        ax.set_title(title, fontsize=14, fontweight="bold")
        ax.grid(True, alpha=0.3, axis="x")

        # Annotate bars
        for bar, val in zip(bars, factor_returns):
            x_pos = bar.get_width() + (0.3 if val >= 0 else -0.3)
            ax.text(x_pos, bar.get_y() + bar.get_height() / 2,
                    f"{val:+.1f}%", va="center", fontsize=9,
                    ha="left" if val >= 0 else "right")

        plt.tight_layout()
        path = self._output_dir / "factor_attribution.png"
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
        return str(path)

    def full_report(
        self,
        equity: list[float],
        dates: Optional[list[str]] = None,
        benchmark: Optional[list[float]] = None,
        monthly_returns: Optional[dict[str, float]] = None,
        factor_names: Optional[list[str]] = None,
        factor_returns: Optional[list[float]] = None,
        stats: Optional[dict] = None,
        title: str = "Backtest Report",
    ) -> str:
        """Generate full HTML backtest report. Returns file path."""
        equity_path = self.equity_curve(equity, dates, benchmark, title)
        dd_path = self.drawdown_chart(equity, dates)
        heatmap_path = (
            self.yearly_heatmap(monthly_returns) if monthly_returns else ""
        )
        attr_path = (
            self.factor_attribution(factor_names, factor_returns)
            if factor_names and factor_returns else ""
        )

        # Build HTML
        stats_html = ""
        if stats:
            stats_html = "<h2>Performance Statistics</h2><table>"
            for k, v in stats.items():
                if isinstance(v, float):
                    stats_html += f"<tr><td>{k}</td><td>{v:.2%}</td></tr>"
                else:
                    stats_html += f"<tr><td>{k}</td><td>{v}</td></tr>"
            stats_html += "</table>"

        charts_html = ""
        for label, path in [
            ("Equity Curve", equity_path),
            ("Drawdown Analysis", dd_path),
            ("Monthly Heatmap", heatmap_path),
            ("Factor Attribution", attr_path),
        ]:
            if path:
                charts_html += f"<h2>{label}</h2><img src='{Path(path).name}' style='max-width:100%'><br>"

        html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
        h1 {{ color: #333; border-bottom: 3px solid #2196F3; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; }}
        table {{ border-collapse: collapse; width: 100%; }}
        td, th {{ padding: 8px 16px; border-bottom: 1px solid #ddd; text-align: left; }}
        tr:nth-child(even) {{ background: #f9f9f9; }}
        img {{ border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin: 10px 0; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    {stats_html}
    {charts_html}
    <p style="color:#999;margin-top:40px">Generated by BacktestVisualizer</p>
</body>
</html>"""

        path = self._output_dir / "report.html"
        path.write_text(html, encoding="utf-8")
        return str(path)

    # ------------------------------------------------------------------
    # ASCII fallbacks
    # ------------------------------------------------------------------

    def _equity_curve_ascii(self, equity: list[float], dates: Optional[list[str]] = None) -> str:
        """ASCII text summary of equity curve."""
        lines = ["=== Equity Curve Summary ==="]
        start_val = equity[0] if equity else 1.0
        end_val = equity[-1] if equity else 1.0
        total_return = (end_val / start_val - 1) * 100
        peak = max(equity)
        max_dd = min((v - peak) / peak for v in equity) * 100
        lines.append(f"Start: {start_val:.4f} | End: {end_val:.4f}")
        lines.append(f"Total Return: {total_return:+.2f}% | Max DD: {max_dd:.1f}%")
        if dates:
            lines.append(f"Period: {dates[0]} → {dates[-1]}")
        result = "\n".join(lines)
        path = self._output_dir / "equity_summary.txt"
        path.write_text(result)
        return str(path)

    def _drawdown_ascii(self, equity: list[float]) -> str:
        return self._equity_curve_ascii(equity)  # Same output

    def _attribution_ascii(self, names: list[str], returns: list[float]) -> str:
        lines = ["=== Factor Attribution ==="]
        for name, ret in zip(names, returns):
            lines.append(f"  {name}: {ret:+.2f}%")
        result = "\n".join(lines)
        path = self._output_dir / "attribution.txt"
        path.write_text(result)
        return str(path)

    def _heatmap_ascii(self, monthly_returns: dict[str, float]) -> str:
        lines = ["=== Monthly Returns ==="]
        for k in sorted(monthly_returns):
            v = monthly_returns[k]
            bar = "█" * min(int(abs(v)), 10)
            sign = "+" if v >= 0 else "-"
            lines.append(f"  {k}: {sign}{bar} {v:+.2f}%")
        result = "\n".join(lines)
        path = self._output_dir / "monthly_returns.txt"
        path.write_text(result)
        return str(path)
