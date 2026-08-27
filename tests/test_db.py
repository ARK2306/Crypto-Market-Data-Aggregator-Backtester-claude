"""Tests for the SQLite layer, backed by a temporary file."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from crypto_backtest import db, utils
from tests.conftest import make_candles


class TestSchema:
    def test_init_creates_table(self, temp_db):
        db.init_db(temp_db)
        with db.connect(temp_db) as conn:
            names = {row["name"] for row in conn.execute("PRAGMA table_info(candles)")}
        assert names == {"symbol", "interval", "date", "close"}

    def test_init_is_idempotent(self, temp_db):
        db.init_db(temp_db)
        db.init_db(temp_db)
        assert db.count_candles(db_path=temp_db) == 0

    def test_creates_parent_directories(self, tmp_path):
        nested = tmp_path / "a" / "b" / "market_data.db"
        db.init_db(nested)
        assert nested.exists()

    def test_connection_rolls_back_on_error(self, temp_db):
        db.init_db(temp_db)
        with pytest.raises(sqlite3.OperationalError):
            with db.connect(temp_db) as conn:
                conn.execute(
                    "INSERT INTO candles VALUES ('BTCUSDT', '1d', '2024-01-01T00:00:00', 1.0)"
                )
                conn.execute("SELECT * FROM nope")
        assert db.count_candles(db_path=temp_db) == 0


class TestUpsert:
    def test_inserts_rows(self, temp_db):
        written = db.upsert_candles("BTCUSDT", "1d", make_candles([100, 101, 102]), db_path=temp_db)
        assert written == 3
        assert db.count_candles("BTCUSDT", "1d", db_path=temp_db) == 3

    def test_empty_input_writes_nothing(self, temp_db):
        assert db.upsert_candles("BTCUSDT", "1d", [], db_path=temp_db) == 0

    def test_reinsert_replaces_close_without_duplicating(self, temp_db):
        candles = make_candles([100, 101])
        db.upsert_candles("BTCUSDT", "1d", candles, db_path=temp_db)
        candles[0]["close"] = 999.0
        db.upsert_candles("BTCUSDT", "1d", candles, db_path=temp_db)
        rows = db.get_candles("BTCUSDT", "1d", db_path=temp_db)
        assert len(rows) == 2 and rows[0]["close"] == 999.0

    def test_same_date_different_symbols_coexist(self, temp_db):
        db.upsert_candles("BTCUSDT", "1d", make_candles([100]), db_path=temp_db)
        db.upsert_candles("ETHUSDT", "1d", make_candles([200]), db_path=temp_db)
        assert db.count_candles(db_path=temp_db) == 2

    def test_same_date_different_intervals_coexist(self, temp_db):
        db.upsert_candles("BTCUSDT", "1d", make_candles([100]), db_path=temp_db)
        db.upsert_candles("BTCUSDT", "4h", make_candles([100]), db_path=temp_db)
        assert db.count_candles("BTCUSDT", db_path=temp_db) == 2

    def test_symbol_is_normalised_on_write(self, temp_db):
        db.upsert_candles("btcusdt", "1d", make_candles([100]), db_path=temp_db)
        assert db.get_candles("BTCUSDT", "1d", db_path=temp_db)

    def test_string_dates_are_accepted(self, temp_db):
        db.upsert_candles(
            "BTCUSDT", "1d", [{"date": "2024-01-01T00:00:00", "close": 100.0}], db_path=temp_db
        )
        rows = db.get_candles("BTCUSDT", "1d", db_path=temp_db)
        assert rows[0]["date"] == datetime(2024, 1, 1, tzinfo=timezone.utc)

    def test_invalid_symbol_rejected(self, temp_db):
        with pytest.raises(ValueError):
            db.upsert_candles("BTC/USDT", "1d", make_candles([100]), db_path=temp_db)


class TestQueries:
    @pytest.fixture
    def populated(self, temp_db):
        db.upsert_candles("BTCUSDT", "1d", make_candles(range(100, 110)), db_path=temp_db)
        return temp_db

    def test_returns_rows_in_chronological_order(self, populated):
        rows = db.get_candles("BTCUSDT", "1d", db_path=populated)
        assert len(rows) == 10
        assert [row["date"] for row in rows] == sorted(row["date"] for row in rows)

    def test_dates_come_back_as_utc_datetimes(self, populated):
        row = db.get_candles("BTCUSDT", "1d", db_path=populated)[0]
        assert isinstance(row["date"], datetime) and row["date"].tzinfo is not None

    def test_start_date_filter(self, populated):
        rows = db.get_candles("BTCUSDT", "1d", start_date="2024-01-05", db_path=populated)
        assert len(rows) == 6

    def test_end_date_filter(self, populated):
        rows = db.get_candles("BTCUSDT", "1d", end_date="2024-01-05", db_path=populated)
        assert len(rows) == 5

    def test_both_filters(self, populated):
        rows = db.get_candles(
            "BTCUSDT", "1d", start_date="2024-01-03", end_date="2024-01-06", db_path=populated
        )
        assert len(rows) == 4

    def test_range_outside_data_returns_empty(self, populated):
        assert db.get_candles(
            "BTCUSDT", "1d", start_date="2030-01-01", end_date="2030-02-01", db_path=populated
        ) == []

    def test_unknown_symbol_returns_empty(self, populated):
        assert db.get_candles("DOGEUSDT", "1d", db_path=populated) == []

    def test_query_on_fresh_database_returns_empty(self, temp_db):
        assert db.get_candles("BTCUSDT", "1d", db_path=temp_db) == []

    def test_date_bounds(self, populated):
        lo, hi = db.get_date_bounds("BTCUSDT", "1d", db_path=populated)
        assert lo == datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert hi == datetime(2024, 1, 10, tzinfo=timezone.utc)

    def test_date_bounds_empty(self, temp_db):
        assert db.get_date_bounds("BTCUSDT", "1d", db_path=temp_db) is None

    def test_delete_removes_only_matching_rows(self, populated):
        db.upsert_candles("ETHUSDT", "1d", make_candles([1, 2]), db_path=populated)
        assert db.delete_candles("BTCUSDT", "1d", db_path=populated) == 10
        assert db.count_candles(db_path=populated) == 2

    def test_roundtrip_preserves_prices(self, temp_db):
        prices = [100.5, 101.25, 99.75]
        db.upsert_candles("BTCUSDT", "1d", make_candles(prices), db_path=temp_db)
        rows = db.get_candles("BTCUSDT", "1d", db_path=temp_db)
        assert [row["close"] for row in rows] == prices
