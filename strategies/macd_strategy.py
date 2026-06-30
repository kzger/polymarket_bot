from __future__ import annotations

import numpy as np
from ta.trend import MACD

from strategies.base_strategy import BaseStrategy, MarketData, Side, Signal


class MACDStrategy(BaseStrategy):
    """MACD Histogram zero-cross strategy.

    Default parameters match the 3/15/3 fast-signal-slow configuration
    commonly used for short-term prediction market price series.
    """

    name = "macd"

    def __init__(
        self,
        fast_period: int = 3,
        slow_period: int = 15,
        signal_period: int = 3,
        order_offset: float = 0.002,
        size: float = 10.0,
    ) -> None:
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self.order_offset = order_offset
        self.size = size

    def generate_signal(self, data: MarketData) -> Signal:
        closes = data.candles["close"]

        if len(closes) < self.slow_period + self.signal_period + 2:
            return Signal(side=Side.HOLD, price=data.market_price, size=self.size, confidence=0.0, strategy_name=self.name)

        macd = MACD(
            close=closes,
            window_fast=self.fast_period,
            window_slow=self.slow_period,
            window_sign=self.signal_period,
        )
        hist = macd.macd_diff().dropna()

        if len(hist) < 2:
            return Signal(side=Side.HOLD, price=data.market_price, size=self.size, confidence=0.0, strategy_name=self.name)

        prev, curr = float(hist.iloc[-2]), float(hist.iloc[-1])

        if prev < 0 and curr >= 0:
            side = Side.BUY
            price = round(max(0.01, data.market_price - self.order_offset), 4)
        elif prev > 0 and curr <= 0:
            side = Side.SELL
            price = round(min(0.99, data.market_price + self.order_offset), 4)
        else:
            return Signal(side=Side.HOLD, price=data.market_price, size=self.size, confidence=0.0, strategy_name=self.name)

        confidence = float(np.clip(abs(curr) / (abs(prev) + 1e-9), 0.0, 1.0))
        return Signal(side=side, price=price, size=self.size, confidence=confidence, strategy_name=self.name)
