"""SQLite persistence for fetched candles."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Union

from . import utils

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "market_data.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol   TEXT NOT NULL,
    interval TEXT NOT NULL,
    date     TEXT NOT NULL,
    close    REAL NOT NULL,
    PRIMARY KEY (symbol, interval, date)
);
CREATE INDEX IF NOT EXISTS idx_candles_lookup
    ON candles (symbol, interval, date);
"""


@contextmanager
def connect(db_path: Union[str, Path] = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Open a connection with row access by name, committing on clean exit."""
    path = Path(db_path).expanduser()
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Union[str, Path] = DEFAULT_DB_PATH) -> None:
    """Create the schema if it does not already exist."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
    logger.debug("Initialised database at %s", db_path)


def _normalise_date(value: Union[str, datetime]) -> str:
    return utils.to_iso(value) if isinstance(value, datetime) else str(value)


def upsert_candles(
    symbol: str,
    interval: str,
    candles: Iterable[Dict[str, Any]],
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> int:
    """Insert or replace candles, keyed on ``(symbol, interval, date)``.

    Returns the number of rows written.
    """
    symbol = utils.validate_symbol(symbol)
    interval = utils.validate_interval(interval)

    rows = [
        (symbol, interval, _normalise_date(candle["date"]), float(candle["close"]))
        for candle in candles
    ]
    if not rows:
        logger.info("No candles to store for %s %s", symbol, interval)
        return 0

    init_db(db_path)
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO candles (symbol, interval, date, close)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol, interval, date) DO UPDATE SET close = excluded.close
            """,
            rows,
        )
    logger.info("Stored %s candles for %s %s", len(rows), symbol, interval)
    return len(rows)


def get_candles(
    symbol: str,
    interval: str,
    start_date: Optional[Union[str, datetime]] = None,
    end_date: Optional[Union[str, datetime]] = None,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> List[Dict[str, Any]]:
    """Query stored candles, optionally bounded by a date range.

    Returns ``{'date': datetime, 'close': float}`` dicts sorted chronologically,
    matching the shape produced by :mod:`crypto_backtest.api`.
    """
    symbol = utils.validate_symbol(symbol)
    interval = utils.validate_interval(interval)
    init_db(db_path)

    query = "SELECT date, close FROM candles WHERE symbol = ? AND interval = ?"
    params: List[Any] = [symbol, interval]
    if start_date is not None:
        query += " AND date >= ?"
        params.append(_normalise_date(utils.parse_date(start_date)))
    if end_date is not None:
        query += " AND date <= ?"
        params.append(_normalise_date(utils.parse_date(end_date)))
    query += " ORDER BY date ASC"

    with connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    return [
        {"date": utils.from_iso(row["date"]), "close": float(row["close"])}
        for row in rows
    ]


def count_candles(
    symbol: Optional[str] = None,
    interval: Optional[str] = None,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> int:
    """Count stored rows, optionally filtered by symbol and/or interval."""
    init_db(db_path)
    query = "SELECT COUNT(*) AS total FROM candles WHERE 1 = 1"
    params: List[Any] = []
    if symbol is not None:
        query += " AND symbol = ?"
        params.append(utils.validate_symbol(symbol))
    if interval is not None:
        query += " AND interval = ?"
        params.append(utils.validate_interval(interval))
    with connect(db_path) as conn:
        return int(conn.execute(query, params).fetchone()["total"])


def get_date_bounds(
    symbol: str,
    interval: str,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> Optional[tuple[datetime, datetime]]:
    """Return the ``(earliest, latest)`` stored candle dates, or ``None``."""
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT MIN(date) AS lo, MAX(date) AS hi FROM candles "
            "WHERE symbol = ? AND interval = ?",
            (utils.validate_symbol(symbol), utils.validate_interval(interval)),
        ).fetchone()
    if row is None or row["lo"] is None:
        return None
    return utils.from_iso(row["lo"]), utils.from_iso(row["hi"])


def delete_candles(
    symbol: str,
    interval: str,
    db_path: Union[str, Path] = DEFAULT_DB_PATH,
) -> int:
    """Delete every stored candle for a symbol/interval pair."""
    init_db(db_path)
    with connect(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM candles WHERE symbol = ? AND interval = ?",
            (utils.validate_symbol(symbol), utils.validate_interval(interval)),
        )
        return cursor.rowcount
