from __future__ import annotations

import time

from data.polymarket_client import PolymarketClient, PolymarketClientError
from strategies.base_strategy import Signal


class OrderManager:
    """Manages limit order lifecycle: placement, deduplication, cancellation."""

    _PRICE_TOLERANCE = 0.001  # orders within this distance are considered duplicates

    def __init__(self, client: PolymarketClient) -> None:
        self._client = client
        # order_id -> {"token_id", "side", "price", "size", "placed_at"}
        self._live_orders: dict[str, dict] = {}

    def place_limit_order(self, token_id: str, signal: Signal) -> str | None:
        """Place a limit order after deduplication check. Returns order_id or None."""
        if self._is_duplicate(token_id, signal):
            return None

        try:
            order_id = self._client.post_limit_order(
                token_id=token_id,
                side=signal.side.value,
                price=signal.price,
                size=signal.size,
            )
            if order_id:
                self._live_orders[order_id] = {
                    "token_id": token_id,
                    "side": signal.side.value,
                    "price": signal.price,
                    "size": signal.size,
                    "placed_at": time.time(),
                }
            return order_id
        except PolymarketClientError:
            return None

    def cancel_stale_orders(self, token_id: str, max_age_seconds: int = 600) -> list[str]:
        """Cancel orders older than max_age_seconds. Returns list of cancelled order IDs."""
        now = time.time()
        to_cancel = [
            oid
            for oid, meta in self._live_orders.items()
            if meta["token_id"] == token_id and (now - meta["placed_at"]) > max_age_seconds
        ]
        cancelled = []
        for oid in to_cancel:
            try:
                if self._client.cancel_order(oid):
                    del self._live_orders[oid]
                    cancelled.append(oid)
            except PolymarketClientError:
                pass
        return cancelled

    def cancel_all(self) -> int:
        """Cancel all open orders. Returns count cancelled."""
        try:
            count = self._client.cancel_all_orders()
            self._live_orders.clear()
            return count
        except PolymarketClientError:
            return 0

    def get_open_orders(self, token_id: str) -> list[dict]:
        try:
            orders = self._client.get_open_orders(token_id)
            # Sync local cache with API response
            api_ids = {o.order_id for o in orders}
            self._live_orders = {
                oid: meta
                for oid, meta in self._live_orders.items()
                if oid in api_ids
            }
            return [
                {"order_id": o.order_id, "side": o.side, "price": o.price, "size": o.size}
                for o in orders
            ]
        except PolymarketClientError:
            return []

    def open_order_count(self, token_id: str) -> int:
        return len(self.get_open_orders(token_id))

    def _is_duplicate(self, token_id: str, signal: Signal) -> bool:
        for meta in self._live_orders.values():
            if (
                meta["token_id"] == token_id
                and meta["side"] == signal.side.value
                and abs(meta["price"] - signal.price) <= self._PRICE_TOLERANCE
            ):
                return True
        return False
