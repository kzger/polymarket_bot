from __future__ import annotations

import numpy as np
import pandas as pd
from ta.momentum import RSIIndicator
from ta.volume import VolumeWeightedAveragePrice

from strategies.base_strategy import BaseStrategy, MarketData, Side, Signal


class RSIMeanReversionStrategy(BaseStrategy):
    """RSI Mean Reversion filtered by VWAP.

    BUY when RSI is oversold AND price is below VWAP (mean-reversion long).
    SELL when RSI is overbought AND price is above VWAP (mean-reversion short).
    """

    name = "rsi_mean_reversion"

    def __init__(
        self,
        rsi_period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        order_offset: float = 0.002,
        size: float = 10.0,
    ) -> None:
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.order_offset = order_offset
        self.size = size

    def generate_signal(self, data: MarketData) -> Signal:
        df = data.candles

        if len(df) < self.rsi_period + 2:
            return Signal(side=Side.HOLD, price=data.market_price, size=self.size, confidence=0.0, strategy_name=self.name)

        rsi_series = RSIIndicator(close=df["close"], window=self.rsi_period).rsi().dropna()
        if rsi_series.empty:
            return Signal(side=Side.HOLD, price=data.market_price, size=self.size, confidence=0.0, strategy_name=self.name)

        rsi = float(rsi_series.iloc[-1])

        vwap_indicator = VolumeWeightedAveragePrice(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            volume=df["volume"],
        )
        vwap_series = vwap_indicator.volume_weighted_average_price().dropna()
        if vwap_series.empty:
            return Signal(side=Side.HOLD, price=data.market_price, size=self.size, confidence=0.0, strategy_name=self.name)

        vwap = float(vwap_series.iloc[-1])
        close = float(df["close"].iloc[-1])

        if rsi < self.oversold and close < vwap:
            side = Side.BUY
            price = round(max(0.01, data.market_price - self.order_offset), 4)
            confidence = float(np.clip((self.oversold - rsi) / self.oversold, 0.0, 1.0))
        elif rsi > self.overbought and close > vwap:
            side = Side.SELL
            price = round(min(0.99, data.market_price + self.order_offset), 4)
            confidence = float(np.clip((rsi - self.overbought) / (100 - self.overbought), 0.0, 1.0))
        else:
            return Signal(side=Side.HOLD, price=data.market_price, size=self.size, confidence=0.0, strategy_name=self.name)

        return Signal(side=side, price=price, size=self.size, confidence=confidence, strategy_name=self.name)
