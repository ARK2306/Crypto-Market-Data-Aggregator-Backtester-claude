"""Typer command line interface."""

from __future__ import annotations

import logging
from typing import Optional

import typer

from . import api, backtest as backtest_module, charts, db, utils

logger = logging.getLogger(__name__)

app = typer.Typer(
    add_completion=False,
    help="Fetch Binance market data, store it locally and backtest an SMA crossover.",
)


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _print_summary(
    result: backtest_module.BacktestResult,
    symbol: str,
    interval: str,
    start,
    end,
    candle_count: int,
    chart_path: str,
    db_path: str,
) -> None:
    typer.echo("")
    typer.echo("=" * 62)
    typer.echo(f" Backtest summary — {symbol} {interval}")
    typer.echo("=" * 62)
    typer.echo(f" Period          : {utils.to_iso(start)} → {utils.to_iso(end)}")
    typer.echo(f" Candles         : {candle_count}")
    typer.echo(f" SMA windows     : {result.short_window} / {result.long_window}")
    typer.echo(f" Initial cash    : {utils.format_currency(result.initial_cash)}")
    typer.echo(f" Final value     : {utils.format_currency(result.final_value)}")
    typer.echo(f" Return          : {utils.format_percent(result.return_pct)}")
    typer.echo(f" Trades executed : {result.trade_count}")
    typer.echo("-" * 62)

    if result.trades:
        typer.echo(f" {'DATE':<12} {'SIDE':<5} {'PRICE':>13} {'UNITS':>14} {'VALUE':>14}")
        for trade in result.trades:
            typer.echo(
                f" {trade.date.strftime('%Y-%m-%d'):<12} {trade.side:<5} "
                f"{trade.price:>13,.2f} {trade.units:>14.6f} {trade.value:>14,.2f}"
            )
    else:
        typer.echo(" No crossover signals were generated in this period.")

    typer.echo("-" * 62)
    typer.echo(f" Database        : {db_path}")
    typer.echo(f" Chart           : {chart_path}")
    typer.echo("=" * 62)


@app.command()
def run(
    symbol: Optional[str] = typer.Option(None, "--symbol", "-s", help="Trading pair, e.g. BTCUSDT."),
    interval: Optional[str] = typer.Option(None, "--interval", "-i", help="Candle interval, e.g. 1d."),
    start_date: Optional[str] = typer.Option(None, "--start-date", help="Start date (YYYY-MM-DD)."),
    end_date: Optional[str] = typer.Option(None, "--end-date", help="End date (YYYY-MM-DD)."),
    short_window: Optional[int] = typer.Option(None, "--short-window", help="Short SMA period."),
    long_window: Optional[int] = typer.Option(None, "--long-window", help="Long SMA period."),
    initial_cash: Optional[float] = typer.Option(None, "--initial-cash", help="Starting capital."),
    db_path: str = typer.Option(db.DEFAULT_DB_PATH, "--db-path", help="SQLite database file."),
    chart_path: str = typer.Option(charts.DEFAULT_CHART_PATH, "--chart-path", help="Chart output file."),
    config_path: Optional[str] = typer.Option(None, "--config", help="Override the config JSON path."),
    lookback_days: int = typer.Option(
        utils.DEFAULT_LOOKBACK_DAYS, "--lookback-days", help="Days to use when dates are omitted."
    ),
    no_chart: bool = typer.Option(False, "--no-chart", help="Skip chart generation."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Fetch data, store it, backtest the SMA crossover and render the chart."""
    _configure_logging(verbose)

    try:
        config = utils.load_config(config_path)
        symbol = utils.validate_symbol(symbol or config["default_symbol"])
        interval = utils.validate_interval(interval or config["default_interval"])
        short = int(short_window if short_window is not None else config["short_window"])
        long = int(long_window if long_window is not None else config["long_window"])
        cash = float(initial_cash if initial_cash is not None else config["initial_cash"])
        utils.validate_windows(short, long)
        start, end = utils.resolve_date_range(start_date, end_date, lookback_days)
    except (utils.ConfigError, ValueError) as exc:
        typer.secho(f"Configuration error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    typer.echo(
        f"Fetching {symbol} {interval} candles from "
        f"{utils.to_iso(start)} to {utils.to_iso(end)}..."
    )

    try:
        candles = api.fetch_klines(symbol, interval, start, end)
    except api.ApiError as exc:
        typer.secho(f"Failed to fetch market data: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if candles:
        stored = db.upsert_candles(symbol, interval, candles, db_path=db_path)
        typer.echo(f"Stored {stored} candles in {db_path}")
    else:
        typer.secho(
            "The API returned no candles; falling back to any stored data.",
            fg=typer.colors.YELLOW,
        )
        db.init_db(db_path)

    rows = db.get_candles(symbol, interval, start, end, db_path=db_path)
    if not rows:
        typer.secho("No data available for this symbol and period.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    result = backtest_module.run_backtest(rows, short, long, cash)

    chart_output = "skipped"
    if not no_chart:
        chart_output = charts.plot_backtest(
            result, symbol=symbol, interval=interval, output_path=chart_path
        )

    _print_summary(result, symbol, interval, start, end, len(rows), chart_output, db_path)


@app.command("show-config")
def show_config(
    config_path: Optional[str] = typer.Option(None, "--config", help="Override the config JSON path.")
) -> None:
    """Print the effective configuration."""
    try:
        config = utils.load_config(config_path)
    except (utils.ConfigError, ValueError) as exc:
        typer.secho(f"Configuration error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    for key, value in config.items():
        typer.echo(f"{key}: {value}")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
