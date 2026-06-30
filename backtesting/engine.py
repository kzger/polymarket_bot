from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config.settings import Settings
from strategies.base_strategy import BaseStrategy, MarketData, Side, Signal


@dataclass
class BacktestTrade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp | None
    side: str
    entry_price: float
    exit_price: float | None
    size: float
    pnl: float


class BacktestEngine:
    """Tick-by-tick backtest engine.

    Reuses the same BaseStrategy objects as the live Trader — no adaptation
    layer. Limit orders are simulated: a BUY fills when the next candle's low
    <= limit price; a SELL fills when the high >= limit price.
    Unfilled orders expire after order_ttl_candles (default 3).
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        candles: pd.DataFrame,
        settings: Settings,
        order_ttl_candles: int = 3,
        token_id: str = "backtest",
    ) -> None:
        self._strategy = strategy
        self._candles = candles.copy().sort_index()
        self._settings = settings
        self._order_ttl = order_ttl_candles
        self._token_id = token_id

    def run(self) -> pd.DataFrame:
        """Replay candles and return a trade log DataFrame."""
        trades: list[BacktestTrade] = []
        pending: dict | None = None  # pending limit order: {side, price, size, entry_time, ttl}

        for i in range(20, len(self._candles)):
            window = self._candles.iloc[: i + 1]
            current = self._candles.iloc[i]

            # Try to fill a pending order on this candle
            if pending is not None:
                filled = False
                if pending["side"] == Side.BUY and current["low"] <= pending["price"]:
                    exit_price = pending["price"]
                    filled = True
                elif pending["side"] == Side.SELL and current["high"] >= pending["price"]:
                    exit_price = pending["price"]
                    filled = True

                if filled:
                    pnl = (
                        (exit_price - pending["entry_price"]) * pending["size"]
                        if pending["side"] == Side.BUY
                        else (pending["entry_price"] - exit_price) * pending["size"]
                    )
                    trades.append(
                        BacktestTrade(
                            entry_time=pending["entry_time"],
                            exit_time=window.index[-1],
                            side=pending["side"].value,
                            entry_price=pending["entry_price"],
                            exit_price=exit_price,
                            size=pending["size"],
                            pnl=pnl,
                        )
                    )
                    pending = None
                else:
                    pending["ttl"] -= 1
                    if pending["ttl"] <= 0:
                        pending = None

            # Only generate a new signal if no pending order
            if pending is None:
                market_price = float(current["close"])
                data = MarketData(
                    token_id=self._token_id,
                    candles=window,
                    order_book={"bids": [], "asks": []},
                    recent_trades=[],
                    market_price=market_price,
                )
                signal: Signal = self._strategy.generate_signal(data)

                if signal.side != Side.HOLD and signal.size >= self._settings.min_order_size_usdc:
                    pending = {
                        "side": signal.side,
                        "price": signal.price,
                        "size": signal.size,
                        "entry_price": signal.price,
                        "entry_time": window.index[-1],
                        "ttl": self._order_ttl,
                    }

        if not trades:
            return pd.DataFrame(columns=["entry_time", "exit_time", "side", "entry_price", "exit_price", "size", "pnl"])

        return pd.DataFrame(
            [
                {
                    "entry_time": t.entry_time,
                    "exit_time": t.exit_time,
                    "side": t.side,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "size": t.size,
                    "pnl": t.pnl,
                }
                for t in trades
            ]
        )
