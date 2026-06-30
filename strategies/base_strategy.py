from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class MarketData:
    """All data available to a strategy on each tick."""

    token_id: str
    candles: pd.DataFrame        # OHLCV from Binance; index = UTC timestamp
    order_book: dict             # {"bids": [...], "asks": [...]}
    recent_trades: list[dict]    # Polymarket trade list
    market_price: float          # Current Polymarket mid price (0–1)


@dataclass
class Signal:
    """Output of a strategy's generate_signal call."""

    side: Side
    price: float          # Limit order price to post on Polymarket
    size: float           # USDC size
    confidence: float     # 0.0–1.0; used for weighted signal combination
    strategy_name: str


class BaseStrategy(ABC):
    """Abstract base for all trading strategies.

    Both the live Trader and the BacktestEngine call generate_signal() using
    the same MarketData type — no adaptation layer required.
    """

    name: str = "base"

    @abstractmethod
    def generate_signal(self, data: MarketData) -> Signal:
        """Compute a trading signal from the current market snapshot."""
        ...
