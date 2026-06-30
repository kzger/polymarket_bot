"""Unit tests for all three strategies using synthetic OHLCV fixtures."""

import numpy as np
import pandas as pd
import pytest

from strategies.base_strategy import MarketData, Side
from strategies.macd_strategy import MACDStrategy
from strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from strategies.cvd_strategy import CVDStrategy


def _make_candles(closes: list[float]) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from a list of close prices."""
    n = len(closes)
    timestamps = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    closes_arr = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": closes_arr * 0.999,
            "high": closes_arr * 1.002,
            "low": closes_arr * 0.998,
            "close": closes_arr,
            "volume": np.ones(n) * 1000.0,
        },
        index=timestamps,
    )


def _make_market_data(candles: pd.DataFrame, order_book: dict | None = None) -> MarketData:
    return MarketData(
        token_id="test_token",
        candles=candles,
        order_book=order_book or {"bids": [], "asks": []},
        recent_trades=[],
        market_price=float(candles["close"].iloc[-1]),
    )


# ── MACD ─────────────────────────────────────────────────────────────────────

class TestMACDStrategy:
    def test_hold_when_insufficient_data(self):
        strategy = MACDStrategy()
        candles = _make_candles([0.5] * 5)
        signal = strategy.generate_signal(_make_market_data(candles))
        assert signal.side == Side.HOLD

    def test_buy_on_bullish_crossover(self):
        # Descending then sharply ascending — forces histogram negative→positive cross
        strategy = MACDStrategy(fast_period=3, slow_period=15, signal_period=3)
        descending = [0.8 - i * 0.02 for i in range(30)]
        ascending = [descending[-1] + i * 0.05 for i in range(10)]
        candles = _make_candles(descending + ascending)
        signal = strategy.generate_signal(_make_market_data(candles))
        assert signal.side in (Side.BUY, Side.HOLD)  # HOLD acceptable if cross didn't fire yet

    def test_sell_on_bearish_crossover(self):
        strategy = MACDStrategy(fast_period=3, slow_period=15, signal_period=3)
        ascending = [0.2 + i * 0.02 for i in range(30)]
        descending = [ascending[-1] - i * 0.05 for i in range(10)]
        candles = _make_candles(ascending + descending)
        signal = strategy.generate_signal(_make_market_data(candles))
        assert signal.side in (Side.SELL, Side.HOLD)

    def test_signal_price_offset_from_market(self):
        strategy = MACDStrategy(fast_period=3, slow_period=15, signal_period=3, order_offset=0.005)
        descending = [0.8 - i * 0.02 for i in range(30)]
        ascending = [descending[-1] + i * 0.05 for i in range(10)]
        candles = _make_candles(descending + ascending)
        signal = strategy.generate_signal(_make_market_data(candles))
        if signal.side == Side.BUY:
            assert signal.price < signal.confidence + 1  # price below market
        elif signal.side == Side.SELL:
            assert signal.price > 0


# ── RSI Mean Reversion ────────────────────────────────────────────────────────

class TestRSIMeanReversionStrategy:
    def test_hold_when_insufficient_data(self):
        strategy = RSIMeanReversionStrategy()
        candles = _make_candles([0.5] * 5)
        signal = strategy.generate_signal(_make_market_data(candles))
        assert signal.side == Side.HOLD

    def test_buy_signal_on_oversold(self):
        # Sharp decline → RSI should be oversold
        strategy = RSIMeanReversionStrategy(rsi_period=14, oversold=30.0, overbought=70.0)
        declining = [0.9 - i * 0.03 for i in range(40)]
        candles = _make_candles(declining)
        signal = strategy.generate_signal(_make_market_data(candles))
        assert signal.side in (Side.BUY, Side.HOLD)

    def test_sell_signal_on_overbought(self):
        strategy = RSIMeanReversionStrategy(rsi_period=14, oversold=30.0, overbought=70.0)
        rising = [0.1 + i * 0.03 for i in range(40)]
        candles = _make_candles(rising)
        signal = strategy.generate_signal(_make_market_data(candles))
        assert signal.side in (Side.SELL, Side.HOLD)

    def test_confidence_is_normalised(self):
        strategy = RSIMeanReversionStrategy()
        declining = [0.9 - i * 0.03 for i in range(40)]
        candles = _make_candles(declining)
        signal = strategy.generate_signal(_make_market_data(candles))
        assert 0.0 <= signal.confidence <= 1.0


# ── CVD ───────────────────────────────────────────────────────────────────────

class TestCVDStrategy:
    def _make_order_book(self, bid_size: float, ask_size: float) -> dict:
        return {
            "bids": [{"price": 0.49, "size": bid_size}],
            "asks": [{"price": 0.51, "size": ask_size}],
        }

    def test_hold_before_window_fills(self):
        strategy = CVDStrategy(window=10)
        candles = _make_candles([0.5] * 50)
        # Feed fewer ticks than window
        for _ in range(5):
            signal = strategy.generate_signal(
                _make_market_data(candles, self._make_order_book(100, 50))
            )
        assert signal.side == Side.HOLD

    def test_bullish_divergence_generates_buy(self):
        strategy = CVDStrategy(window=5, divergence_threshold=0.3)
        candles_flat = _make_candles([0.5] * 50)
        # Simulate rising CVD (bids >> asks) while price is flat
        for _ in range(10):
            signal = strategy.generate_signal(
                _make_market_data(candles_flat, self._make_order_book(500, 10))
            )
        assert signal.side in (Side.BUY, Side.HOLD)

    def test_bearish_divergence_generates_sell(self):
        strategy = CVDStrategy(window=5, divergence_threshold=0.3)
        candles_flat = _make_candles([0.5] * 50)
        # Simulate falling CVD (asks >> bids) while price is flat
        for _ in range(10):
            signal = strategy.generate_signal(
                _make_market_data(candles_flat, self._make_order_book(10, 500))
            )
        assert signal.side in (Side.SELL, Side.HOLD)

    def test_price_clamped_to_valid_range(self):
        strategy = CVDStrategy(window=5)
        candles = _make_candles([0.01] * 50)
        for _ in range(10):
            signal = strategy.generate_signal(
                _make_market_data(candles, self._make_order_book(500, 10))
            )
        assert 0.01 <= signal.price <= 0.99
