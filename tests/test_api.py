"""Tests for the Binance client — every HTTP call is mocked."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests
import responses

from crypto_backtest import api, utils
from tests.conftest import make_klines


def mock_response(payload, status=200):
    """Build a stand-in for a ``requests`` response object."""
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


class TestFetchKlines:
    @responses.activate
    def test_returns_parsed_candles(self, date_range):
        responses.add(
            responses.GET,
            api.BINANCE_KLINES_URL,
            json=make_klines([100, 101, 102]),
            status=200,
        )
        candles = api.fetch_klines("BTCUSDT", "1d", *date_range)
        assert len(candles) == 3
        assert candles[0]["close"] == 100.0
        assert candles[0]["date"] == datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert set(candles[0]) == {"date", "close"}

    @responses.activate
    def test_sends_expected_query_parameters(self, date_range):
        responses.add(responses.GET, api.BINANCE_KLINES_URL, json=[], status=200)
        api.fetch_klines("btcusdt", "1d", *date_range)
        query = responses.calls[0].request.params
        assert query["symbol"] == "BTCUSDT"
        assert query["interval"] == "1d"
        assert query["limit"] == str(api.MAX_LIMIT)
        assert int(query["startTime"]) == utils.to_milliseconds(date_range[0])
        assert int(query["endTime"]) == utils.to_milliseconds(date_range[1])

    @responses.activate
    def test_empty_response_returns_empty_list(self, date_range):
        responses.add(responses.GET, api.BINANCE_KLINES_URL, json=[], status=200)
        assert api.fetch_klines("BTCUSDT", "1d", *date_range) == []

    @responses.activate
    def test_single_candle(self, date_range):
        responses.add(responses.GET, api.BINANCE_KLINES_URL, json=make_klines([42]), status=200)
        candles = api.fetch_klines("BTCUSDT", "1d", *date_range)
        assert len(candles) == 1 and candles[0]["close"] == 42.0

    @responses.activate
    def test_results_are_sorted_chronologically(self, date_range):
        rows = make_klines([100, 101, 102])
        responses.add(
            responses.GET, api.BINANCE_KLINES_URL, json=list(reversed(rows)), status=200
        )
        candles = api.fetch_klines("BTCUSDT", "1d", *date_range)
        assert [candle["date"] for candle in candles] == sorted(
            candle["date"] for candle in candles
        )

    @responses.activate
    def test_malformed_rows_are_skipped(self, date_range):
        rows = make_klines([100]) + [["bad"], "nonsense", [None] * 12]
        responses.add(responses.GET, api.BINANCE_KLINES_URL, json=rows, status=200)
        candles = api.fetch_klines("BTCUSDT", "1d", *date_range)
        assert len(candles) == 1

    @responses.activate
    def test_candles_after_end_time_are_dropped(self):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        responses.add(
            responses.GET, api.BINANCE_KLINES_URL, json=make_klines([1, 2, 3, 4]), status=200
        )
        candles = api.fetch_klines("BTCUSDT", "1d", start, end)
        assert all(candle["date"] <= end for candle in candles)
        assert len(candles) == 2


class TestPagination:
    def test_pages_until_short_page_returned(self, date_range):
        first = make_klines(range(1000))
        second = make_klines(
            range(500), start=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=1000)
        )
        with patch("crypto_backtest.api.requests.get") as get:
            get.side_effect = [mock_response(first), mock_response(second)]
            candles = api.fetch_klines("BTCUSDT", "1d", date_range[0], datetime(2030, 1, 1, tzinfo=timezone.utc))
        assert get.call_count == 2
        assert len(candles) == 1500

    def test_cursor_advances_past_last_candle(self, date_range):
        first = make_klines(range(1000))
        with patch("crypto_backtest.api.requests.get") as get:
            get.side_effect = [mock_response(first), mock_response([])]
            api.fetch_klines("BTCUSDT", "1d", date_range[0], datetime(2030, 1, 1, tzinfo=timezone.utc))
        first_start = get.call_args_list[0].kwargs["params"]["startTime"]
        second_start = get.call_args_list[1].kwargs["params"]["startTime"]
        assert second_start > first_start
        assert second_start == first[-1][0] + 1

    def test_duplicate_pages_do_not_loop_forever(self, date_range):
        page = make_klines(range(1000))
        with patch("crypto_backtest.api.requests.get") as get:
            get.return_value = mock_response(page)
            candles = api.fetch_klines(
                "BTCUSDT", "1d", date_range[0], datetime(2030, 1, 1, tzinfo=timezone.utc)
            )
        # Identical pages are deduplicated by open time, so the walk terminates.
        assert len(candles) == 1000
        assert get.call_count < 10

    def test_single_page_when_fewer_than_limit(self, date_range):
        with patch("crypto_backtest.api.requests.get") as get:
            get.return_value = mock_response(make_klines([1, 2, 3]))
            api.fetch_klines("BTCUSDT", "1d", *date_range)
        assert get.call_count == 1

    def test_limit_is_capped_at_binance_maximum(self, date_range):
        with patch("crypto_backtest.api.requests.get") as get:
            get.return_value = mock_response([])
            api.fetch_klines("BTCUSDT", "1d", *date_range, limit=99999)
        assert get.call_args.kwargs["params"]["limit"] == api.MAX_LIMIT


class TestErrorHandling:
    def test_retries_then_succeeds(self, date_range):
        with patch("crypto_backtest.api.requests.get") as get, patch("crypto_backtest.api.time.sleep"):
            get.side_effect = [
                requests.ConnectionError("boom"),
                mock_response(make_klines([100])),
            ]
            candles = api.fetch_klines("BTCUSDT", "1d", *date_range)
        assert get.call_count == 2 and len(candles) == 1

    def test_raises_after_exhausting_retries(self, date_range):
        with patch("crypto_backtest.api.requests.get") as get, patch("crypto_backtest.api.time.sleep"):
            get.side_effect = requests.Timeout("timed out")
            with pytest.raises(api.ApiError, match="after 3 attempts"):
                api.fetch_klines("BTCUSDT", "1d", *date_range)
        assert get.call_count == 3

    @responses.activate
    def test_http_error_status_raises(self, date_range):
        responses.add(responses.GET, api.BINANCE_KLINES_URL, status=500, json={})
        with patch("crypto_backtest.api.time.sleep"):
            with pytest.raises(api.ApiError):
                api.fetch_klines("BTCUSDT", "1d", *date_range)

    @responses.activate
    def test_binance_error_payload_raises(self, date_range):
        responses.add(
            responses.GET,
            api.BINANCE_KLINES_URL,
            json={"code": -1121, "msg": "Invalid symbol."},
            status=200,
        )
        with pytest.raises(api.ApiError, match="Invalid symbol"):
            api.fetch_klines("BADCOIN", "1d", *date_range)

    def test_invalid_symbol_rejected_before_request(self, date_range):
        with patch("crypto_backtest.api.requests.get") as get:
            with pytest.raises(ValueError):
                api.fetch_klines("BTC-USDT", "1d", *date_range)
        get.assert_not_called()

    def test_invalid_interval_rejected_before_request(self, date_range):
        with patch("crypto_backtest.api.requests.get") as get:
            with pytest.raises(ValueError):
                api.fetch_klines("BTCUSDT", "1y", *date_range)
        get.assert_not_called()

    def test_inverted_date_range_rejected(self):
        with pytest.raises(ValueError):
            api.fetch_klines(
                "BTCUSDT",
                "1d",
                datetime(2024, 6, 1, tzinfo=timezone.utc),
                datetime(2024, 1, 1, tzinfo=timezone.utc),
            )

    def test_naive_datetimes_are_treated_as_utc(self):
        with patch("crypto_backtest.api.requests.get") as get:
            get.return_value = mock_response([])
            api.fetch_klines("BTCUSDT", "1d", datetime(2024, 1, 1), datetime(2024, 2, 1))
        assert get.call_args.kwargs["params"]["startTime"] == utils.to_milliseconds(
            datetime(2024, 1, 1, tzinfo=timezone.utc)
        )

    def test_session_is_used_when_supplied(self, date_range):
        session = MagicMock()
        session.get.return_value = mock_response(make_klines([100]))
        candles = api.fetch_klines("BTCUSDT", "1d", *date_range, session=session)
        assert session.get.called and len(candles) == 1
