"""Long-only SMA crossover backtester."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from . import utils

logger = logging.getLogger(__name__)

BUY = "BUY"
SELL = "SELL"


@dataclass
class Trade:
    """A single executed order."""

    date: datetime
    side: str
    price: float
    units: float
    value: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "side": self.side,
            "price": self.price,
            "units": self.units,
            "value": self.value,
        }


@dataclass
class BacktestResult:
    """Outcome of a backtest run."""

    initial_cash: float
    final_value: float
    return_pct: float
    trades: List[Trade] = field(default_factory=list)
    short_sma: List[Optional[float]] = field(default_factory=list)
    long_sma: List[Optional[float]] = field(default_factory=list)
    dates: List[datetime] = field(default_factory=list)
    prices: List[float] = field(default_factory=list)
    short_window: int = 0
    long_window: int = 0

    @property
    def trade_count(self) -> int:
        return len(self.trades)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "initial_cash": self.initial_cash,
            "final_value": self.final_value,
            "return_pct": self.return_pct,
            "trade_count": self.trade_count,
            "trades": [trade.as_dict() for trade in self.trades],
            "short_sma": self.short_sma,
            "long_sma": self.long_sma,
            "short_window": self.short_window,
            "long_window": self.long_window,
        }


def compute_sma(prices: Sequence[float], window: int) -> List[Optional[float]]:
    """Simple moving average, ``None`` for the leading incomplete window."""
    if window <= 0:
        raise ValueError("window must be a positive integer")

    result: List[Optional[float]] = []
    running = 0.0
    for index, price in enumerate(prices):
        running += price
        if index >= window:
            running -= prices[index - window]
        result.append(running / window if index >= window - 1 else None)
    return result


def _sorted_candles(candles: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Defensively sort candles chronologically and normalise their dates."""
    normalised = []
    for candle in candles:
        date = candle["date"]
        if not isinstance(date, datetime):
            date = utils.parse_date(date)
        normalised.append({"date": utils.ensure_utc(date), "close": float(candle["close"])})
    return sorted(normalised, key=lambda candle: candle["date"])


def run_backtest(
    candles: Sequence[Dict[str, Any]],
    short_window: int = 5,
    long_window: int = 20,
    initial_cash: float = 10000.0,
) -> BacktestResult:
    """Run an SMA crossover backtest over ``candles``.

    Goes all-in when the short SMA crosses above the long SMA and liquidates
    when it crosses back below. Any open position is marked to market using the
    final close. If there are fewer candles than ``long_window`` the strategy
    cannot produce a signal, so the initial cash is returned untouched.
    """
    utils.validate_windows(short_window, long_window)
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")

    rows = _sorted_candles(candles or [])
    dates = [row["date"] for row in rows]
    prices = [row["close"] for row in rows]

    if len(rows) < long_window:
        logger.info(
            "Only %s candles for a %s-period SMA; holding cash",
            len(rows),
            long_window,
        )
        return BacktestResult(
            initial_cash=initial_cash,
            final_value=initial_cash,
            return_pct=0.0,
            trades=[],
            short_sma=[None] * len(rows),
            long_sma=[None] * len(rows),
            dates=dates,
            prices=prices,
            short_window=short_window,
            long_window=long_window,
        )

    short_sma = compute_sma(prices, short_window)
    long_sma = compute_sma(prices, long_window)

    cash = float(initial_cash)
    units = 0.0
    trades: List[Trade] = []
    # None until both SMAs exist; then +1 (short above long) or -1 (below).
    # A strictly trending series never technically crosses, so the first bar
    # with both SMAs defined seeds the state and may itself open a position.
    signal: Optional[int] = None

    for index in range(len(rows)):
        curr_short, curr_long = short_sma[index], long_sma[index]
        if curr_short is None or curr_long is None:
            continue

        if curr_short > curr_long:
            current_signal = 1
        elif curr_short < curr_long:
            current_signal = -1
        else:
            current_signal = signal  # equal SMAs: hold the previous state

        price = prices[index]
        if price <= 0:
            logger.warning("Skipping non-positive price at %s", dates[index])
            continue

        if current_signal == 1 and signal != 1 and cash > 0:
            bought = cash / price
            trades.append(Trade(dates[index], BUY, price, bought, cash))
            units, cash = bought, 0.0
        elif current_signal == -1 and signal != -1 and units > 0:
            proceeds = units * price
            trades.append(Trade(dates[index], SELL, price, units, proceeds))
            cash, units = proceeds, 0.0

        signal = current_signal

    final_value = cash + units * prices[-1]
    return BacktestResult(
        initial_cash=float(initial_cash),
        final_value=final_value,
        return_pct=utils.percent_change(initial_cash, final_value),
        trades=trades,
        short_sma=short_sma,
        long_sma=long_sma,
        dates=dates,
        prices=prices,
        short_window=short_window,
        long_window=long_window,
    )
