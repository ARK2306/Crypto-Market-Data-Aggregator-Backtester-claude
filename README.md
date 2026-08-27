# Crypto Market Data Aggregator & Backtester

A modular Python CLI that fetches historical candlestick data from the public
Binance mirror, stores it in SQLite, backtests an SMA crossover strategy and
renders an annotated chart.

## Layout

| Module | Responsibility |
| --- | --- |
| `crypto_backtest/api.py` | Binance klines client with pagination and retries |
| `crypto_backtest/db.py` | SQLite storage, upserts and range queries |
| `crypto_backtest/backtest.py` | SMA crossover strategy and portfolio simulation |
| `crypto_backtest/charts.py` | Headless (Agg) matplotlib rendering |
| `crypto_backtest/cli.py` | Typer command line interface |
| `crypto_backtest/utils.py` | Config loading, date parsing, validation, formatting |

## Configuration

Defaults are read from `~/.secrets/app_config.json` (override the location with
`--config` or the `APP_CONFIG_PATH` environment variable). Any missing key falls
back to the built-in default.

```json
{
  "default_symbol": "BTCUSDT",
  "default_interval": "1d",
  "short_window": 5,
  "long_window": 20,
  "initial_cash": 10000.0
}
```

## Local usage

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

```bash
.venv/bin/python -m crypto_backtest.cli run --symbol BTCUSDT --interval 1d
```

Dates are optional and default to the last 90 days:

```bash
.venv/bin/python -m crypto_backtest.cli run --symbol ETHUSDT --start-date 2024-01-01 --end-date 2024-06-01
```

Useful options: `--short-window`, `--long-window`, `--initial-cash`, `--db-path`,
`--chart-path`, `--lookback-days`, `--no-chart`, `--verbose`. The
`show-config` command prints the effective configuration.

Outputs: `market_data.db` (SQLite) and `backtest_results.png` (chart).

## Strategy

Long-only, all-in SMA crossover. The strategy buys the full cash balance when
the short SMA sits above the long SMA and liquidates when it drops below. The
first bar where both SMAs are defined seeds the position state, so a series that
trends without ever crossing still opens a position. With fewer candles than
`long_window` no signal exists and the initial cash is returned untouched. Any
open position is marked to market at the final close.

## Tests

```bash
.venv/bin/python -m pytest
```

Every HTTP call is mocked (`responses` / `unittest.mock`) — the suite never
touches the network — and the database tests run against a temporary file.

## Docker

```bash
docker build -t crypto-backtester .
```

```bash
docker run --rm -v "$(pwd)":/data -v "$HOME/.secrets/app_config.json":/home/appuser/.secrets/app_config.json:ro crypto-backtester run --symbol BTCUSDT --interval 1d
```

The container runs as the unprivileged `appuser`, writes its outputs into the
mounted `/data` directory and reads the configuration from the mounted secret.

## CI

`.github/workflows/ci.yml` installs dependencies and runs pytest on every push
to `main` (and on pull requests) across Python 3.10–3.12.
