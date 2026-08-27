"""Headless matplotlib rendering of backtest results."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

import matplotlib

matplotlib.use("Agg")  # must be selected before pyplot is imported

import matplotlib.pyplot as plt  # noqa: E402  (import order is deliberate)
import matplotlib.dates as mdates  # noqa: E402

from .backtest import BUY, BacktestResult  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_CHART_PATH = "backtest_results.png"


def plot_backtest(
    result: BacktestResult,
    symbol: str = "",
    interval: str = "",
    output_path: Union[str, Path] = DEFAULT_CHART_PATH,
    title: Optional[str] = None,
    dpi: int = 120,
) -> str:
    """Plot closes, both SMAs and the buy/sell markers; return the saved path."""
    path = Path(output_path).expanduser()
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)

    figure, axes = plt.subplots(figsize=(13, 7))
    try:
        if not result.dates:
            axes.text(
                0.5,
                0.5,
                "No data available for the requested range",
                ha="center",
                va="center",
                transform=axes.transAxes,
                fontsize=14,
            )
        else:
            axes.plot(
                result.dates, result.prices, label="Close", color="#1f77b4", linewidth=1.4
            )
            _plot_sma(axes, result.dates, result.short_sma, result.short_window, "#ff7f0e")
            _plot_sma(axes, result.dates, result.long_sma, result.long_window, "#2ca02c")
            _plot_trades(axes, result)
            figure.autofmt_xdate()
            axes.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))

        heading = title or _default_title(result, symbol, interval)
        axes.set_title(heading)
        axes.set_xlabel("Date")
        axes.set_ylabel("Price")
        axes.grid(True, alpha=0.3)
        if axes.get_legend_handles_labels()[0]:
            axes.legend(loc="best")
        figure.tight_layout()
        figure.savefig(path, dpi=dpi)
    finally:
        plt.close(figure)

    logger.info("Wrote chart to %s", path)
    return str(path)


def _plot_sma(axes, dates, series, window: int, color: str) -> None:
    """Plot one SMA series, skipping the leading ``None`` values."""
    points = [(date, value) for date, value in zip(dates, series) if value is not None]
    if not points:
        return
    axes.plot(
        [point[0] for point in points],
        [point[1] for point in points],
        label=f"SMA {window}",
        color=color,
        linewidth=1.2,
    )


def _plot_trades(axes, result: BacktestResult) -> None:
    """Mark executed buys and sells."""
    buys = [trade for trade in result.trades if trade.side == BUY]
    sells = [trade for trade in result.trades if trade.side != BUY]
    if buys:
        axes.scatter(
            [trade.date for trade in buys],
            [trade.price for trade in buys],
            marker="^",
            color="#2ca02c",
            s=110,
            zorder=5,
            label=f"Buy ({len(buys)})",
        )
    if sells:
        axes.scatter(
            [trade.date for trade in sells],
            [trade.price for trade in sells],
            marker="v",
            color="#d62728",
            s=110,
            zorder=5,
            label=f"Sell ({len(sells)})",
        )


def _default_title(result: BacktestResult, symbol: str, interval: str) -> str:
    label = " ".join(part for part in (symbol, interval) if part)
    prefix = f"{label} " if label else ""
    return (
        f"{prefix}SMA {result.short_window}/{result.long_window} crossover — "
        f"final ${result.final_value:,.2f} ({result.return_pct:+.2f}%)"
    )
