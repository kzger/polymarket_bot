from __future__ import annotations

from collections import deque

import numpy as np

from strategies.base_strategy import BaseStrategy, MarketData, Side, Signal


class CVDStrategy(BaseStrategy):
    """Cumulative Volume Delta divergence strategy.

    CVD is computed from the Polymarket order book on each poll tick:
        cvd_delta = sum(bid_sizes) - sum(ask_sizes)

    A BUY signal fires when CVD is rising while market_price is flat or falling
    (bullish divergence). A SELL signal fires when CVD is falling while
    market_price is flat or rising (bearish divergence).
    """

    name = "cvd"

    def __init__(
        self,
        window: int = 10,
        divergence_threshold: float = 0.5,
        order_offset: float = 0.002,
        size: float = 10.0,
    ) -> None:
        self.window = window
        self.divergence_threshold = divergence_threshold
        self.order_offset = order_offset
        self.size = size

        self._cvd_series: deque[float] = deque(maxlen=window)
        self._price_series: deque[float] = deque(maxlen=window)

    def _update_state(self, data: MarketData) -> None:
        bids = data.order_book.get("bids", [])
        asks = data.order_book.get("asks", [])
        bid_volume = sum(float(b.get("size", 0)) for b in bids)
        ask_volume = sum(float(a.get("size", 0)) for a in asks)
        self._cvd_series.append(bid_volume - ask_volume)
        self._price_series.append(data.market_price)

    def _trend_slope(self, series: deque[float]) -> float:
        """Return the linear regression slope of the last N values."""
        if len(series) < 3:
            return 0.0
        y = np.array(list(series), dtype=float)
        x = np.arange(len(y), dtype=float)
        slope = float(np.polyfit(x, y, 1)[0])
        return slope

    def generate_signal(self, data: MarketData) -> Signal:
        self._update_state(data)

        if len(self._cvd_series) < self.window:
            return Signal(side=Side.HOLD, price=data.market_price, size=self.size, confidence=0.0, strategy_name=self.name)

        cvd_slope = self._trend_slope(self._cvd_series)
        price_slope = self._trend_slope(self._price_series)

        cvd_std = float(np.std(list(self._cvd_series))) + 1e-9
        normalised_cvd = cvd_slope / cvd_std

        bullish_divergence = normalised_cvd > self.divergence_threshold and price_slope <= 0
        bearish_divergence = normalised_cvd < -self.divergence_threshold and price_slope >= 0

        if bullish_divergence:
            side = Side.BUY
            price = round(max(0.01, data.market_price - self.order_offset), 4)
            confidence = float(np.clip(abs(normalised_cvd) / (self.divergence_threshold * 2), 0.0, 1.0))
        elif bearish_divergence:
            side = Side.SELL
            price = round(min(0.99, data.market_price + self.order_offset), 4)
            confidence = float(np.clip(abs(normalised_cvd) / (self.divergence_threshold * 2), 0.0, 1.0))
        else:
            return Signal(side=Side.HOLD, price=data.market_price, size=self.size, confidence=0.0, strategy_name=self.name)

        return Signal(side=side, price=price, size=self.size, confidence=confidence, strategy_name=self.name)
