from __future__ import annotations

from dataclasses import dataclass

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL


class PolymarketClientError(Exception):
    pass


@dataclass
class OrderBook:
    token_id: str
    bids: list[dict]  # [{"price": float, "size": float}, ...]
    asks: list[dict]


@dataclass
class Trade:
    token_id: str
    side: str  # "BUY" | "SELL"
    price: float
    size: float
    timestamp: int


@dataclass
class Order:
    order_id: str
    token_id: str
    side: str
    price: float
    size: float
    size_matched: float


@dataclass
class Position:
    token_id: str
    size: float
    avg_price: float


class PolymarketClient:
    def __init__(self, client: ClobClient) -> None:
        self._client = client

    def get_order_book(self, token_id: str) -> OrderBook:
        try:
            raw = self._client.get_order_book(token_id)
            bids = [{"price": float(b.price), "size": float(b.size)} for b in raw.bids]
            asks = [{"price": float(a.price), "size": float(a.size)} for a in raw.asks]
            return OrderBook(token_id=token_id, bids=bids, asks=asks)
        except Exception as exc:
            raise PolymarketClientError(f"get_order_book failed: {exc}") from exc

    def get_recent_trades(self, token_id: str, limit: int = 50) -> list[Trade]:
        try:
            raw = self._client.get_trades({"asset_id": token_id, "limit": limit})
            return [
                Trade(
                    token_id=token_id,
                    side=t.get("side", ""),
                    price=float(t.get("price", 0)),
                    size=float(t.get("size", 0)),
                    timestamp=int(t.get("timestamp", 0)),
                )
                for t in (raw or [])
            ]
        except Exception as exc:
            raise PolymarketClientError(f"get_recent_trades failed: {exc}") from exc

    def get_midpoint(self, token_id: str) -> float:
        try:
            result = self._client.get_midpoint(token_id)
            return float(result.get("mid", 0.5))
        except Exception as exc:
            raise PolymarketClientError(f"get_midpoint failed: {exc}") from exc

    def post_limit_order(self, token_id: str, side: str, price: float, size: float) -> str:
        """Place a GTC limit order. Returns the order_id."""
        try:
            clob_side = BUY if side == "BUY" else SELL
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=clob_side,
            )
            signed_order = self._client.create_order(order_args)
            resp = self._client.post_order(signed_order, OrderType.GTC)
            return resp.get("orderID", "")
        except Exception as exc:
            raise PolymarketClientError(f"post_limit_order failed: {exc}") from exc

    def cancel_order(self, order_id: str) -> bool:
        try:
            resp = self._client.cancel(order_id)
            return resp.get("canceled", []) != []
        except Exception as exc:
            raise PolymarketClientError(f"cancel_order failed: {exc}") from exc

    def cancel_all_orders(self) -> int:
        try:
            resp = self._client.cancel_all()
            canceled = resp.get("canceled", [])
            return len(canceled)
        except Exception as exc:
            raise PolymarketClientError(f"cancel_all_orders failed: {exc}") from exc

    def get_open_orders(self, token_id: str) -> list[Order]:
        try:
            raw = self._client.get_orders({"asset_id": token_id, "status": "LIVE"})
            return [
                Order(
                    order_id=o.get("id", ""),
                    token_id=token_id,
                    side=o.get("side", ""),
                    price=float(o.get("price", 0)),
                    size=float(o.get("original_size", 0)),
                    size_matched=float(o.get("size_matched", 0)),
                )
                for o in (raw or [])
            ]
        except Exception as exc:
            raise PolymarketClientError(f"get_open_orders failed: {exc}") from exc

    def get_positions(self) -> list[Position]:
        try:
            raw = self._client.get_positions()
            return [
                Position(
                    token_id=p.get("asset", ""),
                    size=float(p.get("size", 0)),
                    avg_price=float(p.get("avg_price", 0)),
                )
                for p in (raw or [])
            ]
        except Exception as exc:
            raise PolymarketClientError(f"get_positions failed: {exc}") from exc
