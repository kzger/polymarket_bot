from __future__ import annotations

import time

import ccxt
import pandas as pd


def fetch_candles(
    symbol: str,
    interval: str,
    since_ms: int | None = None,
    limit: int = 500,
    exchange_id: str = "binance",
) -> pd.DataFrame:
    """Fetch OHLCV candles from the given exchange.

    Returns a DataFrame with columns: timestamp, open, high, low, close, volume.
    timestamp is a UTC datetime index.
    """
    exchange: ccxt.Exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    raw = exchange.fetch_ohlcv(symbol, timeframe=interval, since=since_ms, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    return df


def fetch_recent_candles(
    symbol: str,
    interval: str,
    n: int = 200,
    exchange_id: str = "binance",
) -> pd.DataFrame:
    """Fetch the most recent n candles. Convenience wrapper for live use."""
    return fetch_candles(symbol=symbol, interval=interval, limit=n, exchange_id=exchange_id)
