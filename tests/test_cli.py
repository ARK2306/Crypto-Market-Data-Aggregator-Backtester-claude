"""End-to-end CLI tests with the Binance API mocked out."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from crypto_backtest import cli, db
from tests.conftest import make_candles

runner = CliRunner()


def recent_candles(count=60, start_price=100):
    """Candles ending today so they fall inside the default 90-day window."""
    start = datetime.now(timezone.utc) - timedelta(days=count)
    return make_candles(range(start_price, start_price + count), start=start)


@pytest.fixture
def workspace(tmp_path, config_file):
    """Paths for an isolated CLI run."""
    return {
        "db": str(tmp_path / "market_data.db"),
        "chart": str(tmp_path / "backtest_results.png"),
        "config": config_file,
    }


def invoke(args, candles, workspace):
    """Run the CLI with ``api.fetch_klines`` patched to return ``candles``."""
    with patch("crypto_backtest.cli.api.fetch_klines", return_value=candles) as fetch:
        result = runner.invoke(
            cli.app,
            ["run", "--db-path", workspace["db"], "--chart-path", workspace["chart"],
             "--config", workspace["config"]] + args,
        )
    return result, fetch


class TestRunCommand:
    def test_successful_run_prints_summary(self, workspace):
        result, _ = invoke(["--symbol", "BTCUSDT"], recent_candles(), workspace)
        assert result.exit_code == 0, result.output
        assert "Backtest summary" in result.output
        assert "Final value" in result.output
        assert "Trades executed" in result.output

    def test_writes_database_and_chart(self, workspace):
        result, _ = invoke([], recent_candles(), workspace)
        assert result.exit_code == 0
        from pathlib import Path

        assert Path(workspace["db"]).exists()
        assert Path(workspace["chart"]).exists()

    def test_candles_are_persisted(self, workspace):
        invoke(["--symbol", "BTCUSDT"], recent_candles(), workspace)
        assert db.count_candles("BTCUSDT", "4h", db_path=workspace["db"]) == 60

    def test_symbol_and_interval_reach_the_api(self, workspace):
        _, fetch = invoke(["--symbol", "ethusdt", "--interval", "1h"], recent_candles(), workspace)
        args = fetch.call_args.args
        assert args[0] == "ETHUSDT" and args[1] == "1h"

    def test_defaults_come_from_config(self, workspace):
        _, fetch = invoke([], recent_candles(), workspace)
        args = fetch.call_args.args
        assert args[0] == "ETHUSDT" and args[1] == "4h"

    def test_default_window_is_ninety_days(self, workspace):
        _, fetch = invoke([], recent_candles(), workspace)
        start, end = fetch.call_args.args[2], fetch.call_args.args[3]
        assert (end - start).days == 90

    def test_explicit_dates_are_used(self, workspace):
        candles = make_candles(
            range(100, 160), start=datetime(2024, 1, 1, tzinfo=timezone.utc)
        )
        result, fetch = invoke(
            ["--start-date", "2024-01-01", "--end-date", "2024-06-01"], candles, workspace
        )
        assert result.exit_code == 0
        assert fetch.call_args.args[2] == datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert fetch.call_args.args[3] == datetime(2024, 6, 1, tzinfo=timezone.utc)

    def test_window_overrides_are_applied(self, workspace):
        result, _ = invoke(
            ["--short-window", "2", "--long-window", "6"], recent_candles(), workspace
        )
        assert "SMA windows     : 2 / 6" in result.output

    def test_initial_cash_override_is_applied(self, workspace):
        result, _ = invoke(["--initial-cash", "500"], recent_candles(), workspace)
        assert "Initial cash    : $500.00" in result.output

    def test_no_chart_flag_skips_rendering(self, workspace):
        from pathlib import Path

        result, _ = invoke(["--no-chart"], recent_candles(), workspace)
        assert result.exit_code == 0
        assert not Path(workspace["chart"]).exists()

    def test_insufficient_data_still_reports(self, workspace):
        result, _ = invoke([], recent_candles(count=5), workspace)
        assert result.exit_code == 0
        assert "No crossover signals" in result.output

    def test_empty_api_response_falls_back_to_stored_data(self, workspace):
        invoke([], recent_candles(), workspace)  # seed the database
        result, _ = invoke([], [], workspace)
        assert result.exit_code == 0
        assert "falling back to any stored data" in result.output
        assert "Backtest summary" in result.output

    def test_empty_api_and_empty_db_exits_with_error(self, workspace):
        result, _ = invoke([], [], workspace)
        assert result.exit_code == 1
        assert "No data available" in result.output

    def test_api_failure_exits_with_error(self, workspace):
        with patch(
            "crypto_backtest.cli.api.fetch_klines",
            side_effect=cli.api.ApiError("network down"),
        ):
            result = runner.invoke(
                cli.app,
                ["run", "--db-path", workspace["db"], "--chart-path", workspace["chart"],
                 "--config", workspace["config"]],
            )
        assert result.exit_code == 1
        assert "Failed to fetch market data" in result.output

    def test_invalid_symbol_exits_with_config_error(self, workspace):
        result, _ = invoke(["--symbol", "BTC/USDT"], recent_candles(), workspace)
        assert result.exit_code == 2
        assert "Configuration error" in result.output

    def test_invalid_interval_exits_with_config_error(self, workspace):
        result, _ = invoke(["--interval", "1y"], recent_candles(), workspace)
        assert result.exit_code == 2

    def test_inverted_dates_exit_with_config_error(self, workspace):
        result, _ = invoke(
            ["--start-date", "2024-06-01", "--end-date", "2024-01-01"],
            recent_candles(),
            workspace,
        )
        assert result.exit_code == 2

    def test_inverted_windows_exit_with_config_error(self, workspace):
        result, _ = invoke(
            ["--short-window", "20", "--long-window", "5"], recent_candles(), workspace
        )
        assert result.exit_code == 2

    def test_rerun_is_idempotent(self, workspace):
        candles = recent_candles()
        invoke([], candles, workspace)
        invoke([], candles, workspace)
        assert db.count_candles("ETHUSDT", "4h", db_path=workspace["db"]) == 60

    def test_trade_table_is_printed_when_trades_occur(self, workspace):
        result, _ = invoke(["--symbol", "BTCUSDT"], recent_candles(), workspace)
        assert "SIDE" in result.output and "BUY" in result.output


class TestShowConfig:
    def test_prints_effective_config(self, workspace):
        result = runner.invoke(cli.app, ["show-config", "--config", workspace["config"]])
        assert result.exit_code == 0
        assert "default_symbol: ETHUSDT" in result.output
        assert "initial_cash: 5000.0" in result.output

    def test_broken_config_exits_with_code_two(self, tmp_path):
        broken = tmp_path / "broken.json"
        broken.write_text("{oops", encoding="utf-8")
        result = runner.invoke(cli.app, ["show-config", "--config", str(broken)])
        assert result.exit_code == 2
        assert "Configuration error" in result.output

    def test_help_lists_the_run_command(self):
        result = runner.invoke(cli.app, ["--help"])
        assert result.exit_code == 0 and "run" in result.output
