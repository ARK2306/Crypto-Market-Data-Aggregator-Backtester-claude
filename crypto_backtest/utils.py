"""Shared helpers: configuration loading, date handling, validation, formatting."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Union

DEFAULT_CONFIG_PATH = Path.home() / ".secrets" / "app_config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "default_symbol": "BTCUSDT",
    "default_interval": "1d",
    "short_window": 5,
    "long_window": 20,
    "initial_cash": 10000.0,
}

# Intervals supported by the Binance klines endpoint.
VALID_INTERVALS = (
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "8h", "12h",
    "1d", "3d", "1w", "1M",
)

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)

DEFAULT_LOOKBACK_DAYS = 90


class ConfigError(Exception):
    """Raised when the configuration file is missing keys or cannot be parsed."""


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def load_config(path: Union[str, Path, None] = None) -> Dict[str, Any]:
    """Load configuration JSON, falling back to built-in defaults per key.

    The path may also be supplied through the APP_CONFIG_PATH environment
    variable, which is how the Docker image points at the mounted secret.
    """
    if path is None:
        path = os.environ.get("APP_CONFIG_PATH", DEFAULT_CONFIG_PATH)
    path = Path(path).expanduser()

    config = dict(DEFAULT_CONFIG)
    if not path.exists():
        return config

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Config file {path} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Config file {path} must contain a JSON object")

    for key in DEFAULT_CONFIG:
        if key in raw and raw[key] is not None:
            config[key] = raw[key]

    config["short_window"] = int(config["short_window"])
    config["long_window"] = int(config["long_window"])
    config["initial_cash"] = float(config["initial_cash"])
    config["default_symbol"] = validate_symbol(config["default_symbol"])
    config["default_interval"] = validate_interval(config["default_interval"])
    validate_windows(config["short_window"], config["long_window"])
    return config


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #
def parse_date(value: Union[str, datetime, None]) -> Optional[datetime]:
    """Parse a user-supplied date into a timezone-aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    if not isinstance(value, str):
        raise ValueError(f"Unsupported date value: {value!r}")

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return ensure_utc(datetime.fromisoformat(text))
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            return ensure_utc(datetime.strptime(text, fmt))
        except ValueError:
            continue
    raise ValueError(f"Could not parse date {value!r}; expected e.g. 2024-01-31")


def ensure_utc(value: datetime) -> datetime:
    """Attach UTC to a naive datetime, or convert an aware one to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_milliseconds(value: datetime) -> int:
    """Convert a datetime to a Binance-style epoch millisecond timestamp."""
    return int(ensure_utc(value).timestamp() * 1000)


def from_milliseconds(value: Union[int, float]) -> datetime:
    """Convert an epoch millisecond timestamp into a UTC datetime."""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def to_iso(value: datetime) -> str:
    """Serialise a datetime for storage in SQLite (sortable UTC ISO-8601)."""
    return ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%S")


def from_iso(value: str) -> datetime:
    """Inverse of :func:`to_iso`."""
    return ensure_utc(datetime.fromisoformat(value))


def default_date_range(
    days: int = DEFAULT_LOOKBACK_DAYS, now: Optional[datetime] = None
) -> tuple[datetime, datetime]:
    """Return the ``(start, end)`` window covering the last ``days`` days."""
    if days <= 0:
        raise ValueError("days must be positive")
    end = ensure_utc(now) if now else datetime.now(timezone.utc)
    return end - timedelta(days=days), end


def resolve_date_range(
    start: Union[str, datetime, None],
    end: Union[str, datetime, None],
    days: int = DEFAULT_LOOKBACK_DAYS,
    now: Optional[datetime] = None,
) -> tuple[datetime, datetime]:
    """Resolve optional CLI dates, defaulting to the last ``days`` days."""
    default_start, default_end = default_date_range(days, now)
    start_dt = parse_date(start) or default_start
    end_dt = parse_date(end) or default_end
    validate_date_range(start_dt, end_dt)
    return start_dt, end_dt


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def validate_symbol(symbol: str) -> str:
    """Normalise a trading symbol to upper case and reject junk input."""
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("Symbol must be a non-empty string")
    normalised = symbol.strip().upper()
    if not normalised.isalnum():
        raise ValueError(f"Symbol {symbol!r} must be alphanumeric, e.g. BTCUSDT")
    return normalised


def validate_interval(interval: str) -> str:
    """Reject intervals the Binance endpoint does not understand."""
    if not isinstance(interval, str):
        raise ValueError("Interval must be a string")
    normalised = interval.strip()
    if normalised not in VALID_INTERVALS:
        raise ValueError(
            f"Interval {interval!r} is not supported; choose one of "
            + ", ".join(VALID_INTERVALS)
        )
    return normalised


def validate_date_range(start: datetime, end: datetime) -> None:
    """Ensure the requested window is ordered."""
    if ensure_utc(start) >= ensure_utc(end):
        raise ValueError(
            f"start_date ({to_iso(start)}) must be before end_date ({to_iso(end)})"
        )


def validate_windows(short_window: int, long_window: int) -> None:
    """Ensure the SMA windows are usable."""
    if short_window <= 0 or long_window <= 0:
        raise ValueError("SMA windows must be positive integers")
    if short_window >= long_window:
        raise ValueError(
            f"short_window ({short_window}) must be smaller than "
            f"long_window ({long_window})"
        )


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #
def format_currency(value: float, symbol: str = "$") -> str:
    """Format a monetary amount with thousands separators and two decimals."""
    return f"{symbol}{value:,.2f}"


def format_percent(value: float, decimals: int = 2) -> str:
    """Format a percentage with an explicit sign."""
    return f"{value:+.{decimals}f}%"


def percent_change(start_value: float, end_value: float) -> float:
    """Percentage change between two values; 0.0 when the base is zero."""
    if start_value == 0:
        return 0.0
    return (end_value - start_value) / start_value * 100.0


def chunked(items: Iterable[Any], size: int) -> Iterable[list]:
    """Yield lists of at most ``size`` items (used for batched DB writes)."""
    if size <= 0:
        raise ValueError("size must be positive")
    batch: list = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch
