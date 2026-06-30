from __future__ import annotations

import time
from collections import Counter

from config.settings import Settings
from data.downloader import fetch_recent_candles
from data.polymarket_client import PolymarketClient, PolymarketClientError
from strategies.base_strategy import BaseStrategy, MarketData, Side, Signal
from bot.order_manager import OrderManager
from bot.position_tracker import PositionTracker
from bot.risk_manager import RiskManager
from incubation.logger import TradeLogger
from incubation.scaler import Scaler


class Trader:
    """Main polling loop. Owns the strategy registry and orchestrates execution."""

    def __init__(
        self,
        settings: Settings,
        client: PolymarketClient,
        watched_markets: list[str],
        scaler: Scaler | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._watched_markets = watched_markets

        self._position_tracker = PositionTracker()
        self._risk_manager = RiskManager(settings, self._position_tracker)
        self._order_manager = OrderManager(client)
        self._logger = TradeLogger()
        self._scaler = scaler
        self._strategies: list[BaseStrategy] = []

    def register_strategy(self, strategy: BaseStrategy) -> None:
        self._strategies.append(strategy)

    def run(self) -> None:
        print(f"[Trader] Starting polling loop — interval={self._settings.poll_interval_seconds}s, markets={self._watched_markets}")
        while True:
            for token_id in self._watched_markets:
                try:
                    self._tick(token_id)
                except Exception as exc:
                    self._logger.log_error(f"tick error for {token_id}", exc)
            time.sleep(self._settings.poll_interval_seconds)

    def _tick(self, token_id: str) -> None:
        data = self._fetch_market_data(token_id)

        signals = [s.generate_signal(data) for s in self._strategies]
        combined = self._combine_signals(signals, data.market_price)

        if self._scaler:
            combined.size = self._scaler.get_current_size(combined.strategy_name)

        open_count = self._order_manager.open_order_count(token_id)
        self._risk_manager.set_open_order_count(open_count)

        approved, reason = self._risk_manager.validate(combined, token_id)
        self._logger.log_signal(token_id, combined, approved, reason)

        if approved:
            order_id = self._order_manager.place_limit_order(token_id, combined)
            if order_id:
                print(f"[Trader] Placed {combined.side.value} @ {combined.price} size={combined.size} order_id={order_id}")

        self._order_manager.cancel_stale_orders(token_id)

    def _fetch_market_data(self, token_id: str) -> MarketData:
        candles = fetch_recent_candles(
            symbol=self._settings.binance_symbol,
            interval=self._settings.candle_interval,
            n=200,
        )
        order_book = self._client.get_order_book(token_id)
        recent_trades = self._client.get_recent_trades(token_id, limit=50)
        market_price = self._client.get_midpoint(token_id)

        return MarketData(
            token_id=token_id,
            candles=candles,
            order_book={"bids": order_book.bids, "asks": order_book.asks},
            recent_trades=[{"side": t.side, "price": t.price, "size": t.size} for t in recent_trades],
            market_price=market_price,
        )

    def _combine_signals(self, signals: list[Signal], market_price: float) -> Signal:
        """Combine multiple strategy signals via majority vote.

        Side: whichever side (BUY/SELL/HOLD) appears most often wins.
        Price: confidence-weighted average of non-HOLD signal prices.
        Size: sum of non-HOLD signal sizes (risk manager caps the total).
        Confidence: mean of non-HOLD confidences.

        TODO: You can replace this combiner with a stricter "all must agree"
        rule, a weighted-vote scheme, or a per-strategy allocation model.
        """
        if not signals:
            return Signal(side=Side.HOLD, price=market_price, size=0.0, confidence=0.0, strategy_name="combined")

        side_votes = Counter(s.side for s in signals)
        winning_side = side_votes.most_common(1)[0][0]

        active = [s for s in signals if s.side == winning_side and s.side != Side.HOLD]

        if not active:
            return Signal(side=Side.HOLD, price=market_price, size=0.0, confidence=0.0, strategy_name="combined")

        total_conf = sum(s.confidence for s in active) or 1.0
        weighted_price = sum(s.price * s.confidence for s in active) / total_conf
        total_size = sum(s.size for s in active)
        mean_conf = total_conf / len(active)

        return Signal(
            side=winning_side,
            price=round(weighted_price, 4),
            size=round(total_size, 2),
            confidence=mean_conf,
            strategy_name="combined",
        )
