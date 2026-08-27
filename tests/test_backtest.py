"""Tests for the SMA crossover strategy."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crypto_backtest import backtest
from tests.conftest import make_candles


class TestComputeSma:
    def test_leading_values_are_none(self):
        assert backtest.compute_sma([1, 2, 3, 4], 3)[:2] == [None, None]

    def test_values_are_correct(self):
        assert backtest.compute_sma([1, 2, 3, 4], 3) == [None, None, 2.0, 3.0]

    def test_window_of_one_returns_prices(self):
        assert backtest.compute_sma([5, 6, 7], 1) == [5.0, 6.0, 7.0]

    def test_window_longer_than_series_is_all_none(self):
        assert backtest.compute_sma([1, 2], 5) == [None, None]

    def test_empty_prices(self):
        assert backtest.compute_sma([], 3) == []

    def test_length_matches_input(self):
        assert len(backtest.compute_sma(list(range(50)), 20)) == 50

    def test_non_positive_window_raises(self):
        with pytest.raises(ValueError):
            backtest.compute_sma([1, 2, 3], 0)


class TestEdgeCases:
    def test_empty_candles_returns_initial_cash(self):
        result = backtest.run_backtest([], 5, 20, 10000.0)
        assert result.final_value == 10000.0
        assert result.trades == []
        assert result.return_pct == 0.0

    def test_single_candle_returns_initial_cash(self):
        result = backtest.run_backtest(make_candles([100]), 5, 20, 10000.0)
        assert result.final_value == 10000.0 and result.trades == []

    def test_fewer_candles_than_long_window(self):
        result = backtest.run_backtest(make_candles(range(100, 119)), 5, 20, 10000.0)
        assert result.final_value == 10000.0
        assert result.trades == []
        assert result.short_sma == [None] * 19

    def test_exactly_long_window_candles_enters_on_final_bar(self):
        # The first bar with both SMAs seeds the state; here that is the last bar,
        # so the buy is immediately marked to market at the same price.
        result = backtest.run_backtest(make_candles(range(100, 120)), 5, 20, 10000.0)
        assert result.short_sma[19] is not None
        assert [trade.side for trade in result.trades] == [backtest.BUY]
        assert result.final_value == pytest.approx(10000.0)

    def test_flat_market_produces_no_trades(self):
        result = backtest.run_backtest(make_candles([100] * 60), 5, 20, 10000.0)
        assert result.trades == []
        assert result.final_value == 10000.0

    def test_invalid_windows_raise(self):
        with pytest.raises(ValueError):
            backtest.run_backtest(make_candles([1, 2, 3]), 20, 5)

    def test_non_positive_cash_raises(self):
        with pytest.raises(ValueError):
            backtest.run_backtest(make_candles([1, 2, 3]), 5, 20, 0)

    def test_string_dates_are_parsed(self):
        candles = [{"date": f"2024-01-{day:02d}", "close": 100.0} for day in range(1, 26)]
        result = backtest.run_backtest(candles, 5, 20, 10000.0)
        assert isinstance(result.dates[0], datetime)

    def test_unsorted_candles_are_sorted(self):
        candles = list(reversed(make_candles(range(100, 130))))
        result = backtest.run_backtest(candles, 5, 20, 10000.0)
        assert result.dates == sorted(result.dates)


class TestStrategy:
    def test_pure_uptrend_buys_once_and_holds(self):
        result = backtest.run_backtest(make_candles(range(100, 160)), 5, 20, 10000.0)
        assert len(result.trades) == 1
        assert result.trades[0].side == backtest.BUY
        assert result.final_value > 10000.0

    def test_pure_downtrend_never_buys(self):
        result = backtest.run_backtest(make_candles(range(200, 140, -1)), 5, 20, 10000.0)
        assert result.trades == []
        assert result.final_value == 10000.0

    def test_up_then_down_produces_buy_then_sell(self):
        prices = list(range(100, 160)) + list(range(160, 100, -1))
        result = backtest.run_backtest(make_candles(prices), 5, 20, 10000.0)
        sides = [trade.side for trade in result.trades]
        assert sides[0] == backtest.BUY
        assert backtest.SELL in sides
        for first, second in zip(sides, sides[1:]):
            assert first != second  # sides must alternate

    def test_trades_carry_all_required_fields(self):
        result = backtest.run_backtest(make_candles(range(100, 160)), 5, 20, 10000.0)
        trade = result.trades[0].as_dict()
        assert set(trade) == {"date", "side", "price", "units", "value"}
        assert trade["units"] > 0 and trade["price"] > 0

    def test_buy_spends_all_cash(self):
        result = backtest.run_backtest(make_candles(range(100, 160)), 5, 20, 10000.0)
        trade = result.trades[0]
        assert trade.units * trade.price == pytest.approx(10000.0)

    def test_sell_liquidates_entire_position(self):
        prices = list(range(100, 160)) + list(range(160, 100, -1))
        result = backtest.run_backtest(make_candles(prices), 5, 20, 10000.0)
        buy = result.trades[0]
        sell = next(trade for trade in result.trades if trade.side == backtest.SELL)
        assert sell.units == pytest.approx(buy.units)

    def test_no_double_buy_while_holding(self):
        prices = list(range(100, 200))
        result = backtest.run_backtest(make_candles(prices), 5, 20, 10000.0)
        assert [trade.side for trade in result.trades].count(backtest.BUY) == 1

    def test_open_position_is_marked_to_market(self):
        result = backtest.run_backtest(make_candles(range(100, 160)), 5, 20, 10000.0)
        buy = result.trades[0]
        assert result.final_value == pytest.approx(buy.units * 159.0)

    def test_return_pct_matches_final_value(self):
        result = backtest.run_backtest(make_candles(range(100, 160)), 5, 20, 10000.0)
        expected = (result.final_value - 10000.0) / 10000.0 * 100
        assert result.return_pct == pytest.approx(expected)

    def test_sma_series_lengths_match_candles(self):
        candles = make_candles(range(100, 160))
        result = backtest.run_backtest(candles, 5, 20, 10000.0)
        assert len(result.short_sma) == len(candles)
        assert len(result.long_sma) == len(candles)

    def test_initial_cash_is_respected(self):
        result = backtest.run_backtest(make_candles(range(100, 160)), 5, 20, 250.0)
        assert result.initial_cash == 250.0
        assert result.trades[0].value == pytest.approx(250.0)

    def test_result_as_dict_shape(self):
        result = backtest.run_backtest(make_candles(range(100, 160)), 5, 20, 10000.0)
        payload = result.as_dict()
        assert payload["trade_count"] == len(result.trades)
        assert payload["short_window"] == 5 and payload["long_window"] == 20

    def test_trade_count_property(self):
        result = backtest.run_backtest(make_candles(range(100, 160)), 5, 20, 10000.0)
        assert result.trade_count == len(result.trades)

    def test_custom_windows_generate_more_trades(self):
        prices = [100 + (10 if index % 8 < 4 else -10) for index in range(120)]
        wide = backtest.run_backtest(make_candles(prices), 5, 20, 10000.0)
        tight = backtest.run_backtest(make_candles(prices), 2, 4, 10000.0)
        assert tight.trade_count >= wide.trade_count
