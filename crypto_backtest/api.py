"""Binance market-data client with transparent pagination."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from . import utils

logger = logging.getLogger(__name__)

BINANCE_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"

#: Binance never returns more than 1000 candles per request.
MAX_LIMIT = 1000
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0

# Index of the fields we care about inside a raw kline row.
OPEN_TIME_INDEX = 0
CLOSE_PRICE_INDEX = 4


class ApiError(Exception):
    """Raised when the Binance endpoint cannot be reached or returns an error."""


def _request_page(
    url: str,
    params: Dict[str, Any],
    timeout: int,
    max_retries: int,
    retry_delay: float,
    session: Optional[requests.Session] = None,
) -> List[list]:
    """Fetch a single page of klines, retrying transient failures."""
    getter = session.get if session is not None else requests.get
    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            response = getter(url, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            last_error = exc
            logger.warning(
                "Binance request failed (attempt %s/%s): %s", attempt, max_retries, exc
            )
        except ValueError as exc:  # malformed JSON body
            last_error = ApiError(f"Binance returned a non-JSON response: {exc}")
            logger.warning("Binance returned malformed JSON: %s", exc)
        else:
            if isinstance(payload, dict):
                # Binance reports application-level problems as {"code": .., "msg": ..}
                raise ApiError(
                    f"Binance error {payload.get('code')}: {payload.get('msg')}"
                )
            if not isinstance(payload, list):
                raise ApiError(f"Unexpected payload type from Binance: {type(payload)}")
            return payload

        if attempt < max_retries:
            time.sleep(retry_delay * attempt)

    raise ApiError(f"Failed to fetch klines after {max_retries} attempts: {last_error}")


def _parse_row(row: list) -> Optional[Dict[str, Any]]:
    """Convert a raw kline row into ``{'date': datetime, 'close': float}``."""
    if not isinstance(row, (list, tuple)) or len(row) <= CLOSE_PRICE_INDEX:
        logger.warning("Skipping malformed kline row: %r", row)
        return None
    try:
        open_time = int(row[OPEN_TIME_INDEX])
        close = float(row[CLOSE_PRICE_INDEX])
    except (TypeError, ValueError):
        logger.warning("Skipping unparseable kline row: %r", row)
        return None
    return {"date": utils.from_milliseconds(open_time), "close": close}


def fetch_klines(
    symbol: str,
    interval: str,
    start_date: datetime,
    end_date: datetime,
    *,
    limit: int = MAX_LIMIT,
    url: str = BINANCE_KLINES_URL,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    """Fetch every candle for ``symbol`` between ``start_date`` and ``end_date``.

    Binance caps each response at 1000 candles, so this walks the window
    forward one page at a time until the endpoint runs out of data.

    Returns a chronologically sorted list of ``{'date': datetime, 'close': float}``.
    """
    symbol = utils.validate_symbol(symbol)
    interval = utils.validate_interval(interval)
    start_dt = utils.ensure_utc(start_date)
    end_dt = utils.ensure_utc(end_date)
    utils.validate_date_range(start_dt, end_dt)
    limit = max(1, min(int(limit), MAX_LIMIT))

    start_ms = utils.to_milliseconds(start_dt)
    end_ms = utils.to_milliseconds(end_dt)

    candles: Dict[int, Dict[str, Any]] = {}
    cursor = start_ms
    pages = 0

    while cursor <= end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": limit,
        }
        rows = _request_page(url, params, timeout, max_retries, retry_delay, session)
        pages += 1
        if not rows:
            break

        last_open_time: Optional[int] = None
        for row in rows:
            parsed = _parse_row(row)
            if parsed is None:
                continue
            open_ms = utils.to_milliseconds(parsed["date"])
            last_open_time = open_ms if last_open_time is None else max(last_open_time, open_ms)
            if open_ms > end_ms:
                continue
            candles[open_ms] = parsed

        if last_open_time is None or last_open_time < cursor:
            # Nothing usable came back, or the endpoint is repeating itself.
            break

        cursor = last_open_time + 1
        if len(rows) < limit:
            break

    logger.info(
        "Fetched %s candles for %s %s across %s page(s)",
        len(candles),
        symbol,
        interval,
        pages,
    )
    return [candles[key] for key in sorted(candles)]


#: Descriptive alias used by the CLI and tests.
fetch_historical_data = fetch_klines
