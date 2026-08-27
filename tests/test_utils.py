"""Tests for the shared helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from crypto_backtest import utils


class TestConfig:
    def test_loads_values_from_file(self, config_file):
        config = utils.load_config(config_file)
        assert config["default_symbol"] == "ETHUSDT"
        assert config["default_interval"] == "4h"
        assert config["short_window"] == 3
        assert config["long_window"] == 10
        assert config["initial_cash"] == 5000.0

    def test_missing_file_falls_back_to_defaults(self, tmp_path):
        config = utils.load_config(tmp_path / "does_not_exist.json")
        assert config == utils.DEFAULT_CONFIG

    def test_partial_file_is_merged_with_defaults(self, tmp_path):
        path = tmp_path / "partial.json"
        path.write_text(json.dumps({"default_symbol": "solusdt"}), encoding="utf-8")
        config = utils.load_config(path)
        assert config["default_symbol"] == "SOLUSDT"
        assert config["long_window"] == utils.DEFAULT_CONFIG["long_window"]

    def test_invalid_json_raises_config_error(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(utils.ConfigError):
            utils.load_config(path)

    def test_non_object_json_raises_config_error(self, tmp_path):
        path = tmp_path / "list.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(utils.ConfigError):
            utils.load_config(path)

    def test_inverted_windows_rejected(self, tmp_path):
        path = tmp_path / "bad_windows.json"
        path.write_text(json.dumps({"short_window": 30, "long_window": 10}), encoding="utf-8")
        with pytest.raises(ValueError):
            utils.load_config(path)

    def test_env_var_supplies_path(self, config_file, monkeypatch):
        monkeypatch.setenv("APP_CONFIG_PATH", config_file)
        assert utils.load_config()["default_symbol"] == "ETHUSDT"


class TestDates:
    @pytest.mark.parametrize(
        "value",
        ["2024-03-15", "2024/03/15", "15-03-2024", "2024-03-15 00:00:00", "2024-03-15T00:00:00"],
    )
    def test_parses_supported_formats(self, value):
        assert utils.parse_date(value) == datetime(2024, 3, 15, tzinfo=timezone.utc)

    def test_parses_trailing_z(self):
        assert utils.parse_date("2024-03-15T06:30:00Z") == datetime(
            2024, 3, 15, 6, 30, tzinfo=timezone.utc
        )

    def test_none_and_empty_return_none(self):
        assert utils.parse_date(None) is None
        assert utils.parse_date("") is None

    def test_datetime_passthrough_gets_utc(self):
        assert utils.parse_date(datetime(2024, 3, 15)).tzinfo == timezone.utc

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            utils.parse_date("not-a-date")

    def test_millisecond_roundtrip(self):
        moment = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
        assert utils.from_milliseconds(utils.to_milliseconds(moment)) == moment

    def test_iso_roundtrip(self):
        moment = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
        assert utils.from_iso(utils.to_iso(moment)) == moment

    def test_iso_strings_sort_chronologically(self):
        early = utils.to_iso(datetime(2024, 1, 9, tzinfo=timezone.utc))
        late = utils.to_iso(datetime(2024, 1, 10, tzinfo=timezone.utc))
        assert early < late

    def test_default_range_is_ninety_days(self):
        now = datetime(2024, 6, 1, tzinfo=timezone.utc)
        start, end = utils.default_date_range(now=now)
        assert end == now
        assert (end - start).days == 90

    def test_default_range_rejects_non_positive_days(self):
        with pytest.raises(ValueError):
            utils.default_date_range(days=0)

    def test_resolve_range_uses_defaults_when_omitted(self):
        now = datetime(2024, 6, 1, tzinfo=timezone.utc)
        start, end = utils.resolve_date_range(None, None, now=now)
        assert (end - start).days == 90

    def test_resolve_range_honours_explicit_dates(self):
        start, end = utils.resolve_date_range("2024-01-01", "2024-02-01")
        assert start == datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert end == datetime(2024, 2, 1, tzinfo=timezone.utc)

    def test_resolve_range_rejects_inverted_dates(self):
        with pytest.raises(ValueError):
            utils.resolve_date_range("2024-02-01", "2024-01-01")


class TestValidation:
    def test_symbol_is_upper_cased(self):
        assert utils.validate_symbol(" btcusdt ") == "BTCUSDT"

    @pytest.mark.parametrize("value", ["", "   ", "BTC-USDT", "BTC/USDT", None, 42])
    def test_bad_symbols_rejected(self, value):
        with pytest.raises(ValueError):
            utils.validate_symbol(value)

    def test_valid_interval_accepted(self):
        assert utils.validate_interval("1d") == "1d"

    @pytest.mark.parametrize("value", ["1y", "daily", "", 5])
    def test_bad_intervals_rejected(self, value):
        with pytest.raises(ValueError):
            utils.validate_interval(value)

    def test_windows_must_be_ordered_and_positive(self):
        utils.validate_windows(5, 20)
        with pytest.raises(ValueError):
            utils.validate_windows(20, 5)
        with pytest.raises(ValueError):
            utils.validate_windows(5, 5)
        with pytest.raises(ValueError):
            utils.validate_windows(0, 20)


class TestFormatting:
    def test_currency_formatting(self):
        assert utils.format_currency(1234567.891) == "$1,234,567.89"

    def test_percent_formatting_is_signed(self):
        assert utils.format_percent(12.3456) == "+12.35%"
        assert utils.format_percent(-4.2) == "-4.20%"

    def test_percent_change(self):
        assert utils.percent_change(100, 150) == pytest.approx(50.0)
        assert utils.percent_change(100, 75) == pytest.approx(-25.0)

    def test_percent_change_with_zero_base(self):
        assert utils.percent_change(0, 100) == 0.0

    def test_chunked_splits_evenly_and_remainder(self):
        assert list(utils.chunked(range(5), 2)) == [[0, 1], [2, 3], [4]]
        assert list(utils.chunked([], 3)) == []
        with pytest.raises(ValueError):
            list(utils.chunked([1], 0))
