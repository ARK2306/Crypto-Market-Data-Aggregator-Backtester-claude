"""Shared pytest fixtures."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crypto_backtest import utils  # noqa: E402


def make_candles(prices, start=None, step_days=1):
    """Build ``{'date', 'close'}`` dicts from a list of prices."""
    start = start or datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        {"date": start + timedelta(days=index * step_days), "close": float(price)}
        for index, price in enumerate(prices)
    ]


def make_klines(prices, start=None, step_ms=86_400_000):
    """Build raw Binance kline rows for the given closes."""
    start_ms = utils.to_milliseconds(start or datetime(2024, 1, 1, tzinfo=timezone.utc))
    rows = []
    for index, price in enumerate(prices):
        open_time = start_ms + index * step_ms
        rows.append(
            [
                open_time,
                str(price),          # open
                str(price),          # high
                str(price),          # low
                str(price),          # close
                "1.0",               # volume
                open_time + step_ms - 1,
                "1000.0", 10, "0.5", "500.0", "0",
            ]
        )
    return rows


@pytest.fixture
def temp_db(tmp_path):
    """Path to a throwaway SQLite database file."""
    return str(tmp_path / "test_market_data.db")


@pytest.fixture
def config_file(tmp_path):
    """A valid config JSON on disk."""
    path = tmp_path / "app_config.json"
    path.write_text(
        json.dumps(
            {
                "default_symbol": "ETHUSDT",
                "default_interval": "4h",
                "short_window": 3,
                "long_window": 10,
                "initial_cash": 5000.0,
            }
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
def date_range():
    """A one-year UTC window."""
    return (
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 12, 31, tzinfo=timezone.utc),
    )
