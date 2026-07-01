"""Immutable fill ledger → inventory bridge (WS-C) — Contract #4.

Folds Contract #1b parsed trade events into :class:`~mm_v2.domain.fill.Fill`
records. Inventory is *derived* from the immutable ledger, never a mutated
running total (PLAN §3.2).

This module is the one place allowed to depend on BOTH feeds and domain. The
two derive functions enforce Contract #4 at the boundary:

* ``derive_logical_fills`` — one :class:`LogicalFill` per ``maker_orders[]``
  entry, keyed ``(trade_id, maker_order_id)``. Identity is stable across the WS
  frame and the later REST record for the same trade.
* ``derive_settlement_buckets`` — a settlement bucket exists ONLY when REST/
  on-chain metadata is present. A WS frame yields none; we never fabricate a
  ``bucket_index`` / ``transaction_hash`` the wire did not carry.
"""

from __future__ import annotations

from mm_v2.domain.fill import (
    LogicalFill,
    SettlementBucket,
    StatusScope,
)
from mm_v2.domain.order import Side, TradeSideConvention
from mm_v2.feeds.events import RestMakerOrderFill, RestTradeEvent, UserTradeWsEvent

type TradeEvent = UserTradeWsEvent | RestTradeEvent


def _opposite_side(side: Side) -> Side:
    """The maker side is the opposite of the taker side of the trade."""
    return Side.SELL if side is Side.BUY else Side.BUY


def _ws_maker_side(taker_side: Side, convention: TradeSideConvention) -> Side:
    """Interpret a WS trade's ``side`` into the maker fill side (PLAN §8).

    Unproven until an M0 controlled probe freezes it, so the interpretation is a
    caller knob rather than a hard-coded fact.
    """
    if convention is TradeSideConvention.TAKER_SIDE:
        return _opposite_side(taker_side)
    return taker_side


def derive_logical_fills(
    trade: TradeEvent,
    *,
    ws_side_convention: TradeSideConvention = TradeSideConvention.TAKER_SIDE,
) -> list[LogicalFill]:
    """Derive one logical fill per maker order matched in the trade.

    The logical-fill key ``(trade_id, maker_order_id)`` is identical whether the
    trade arrives via WS or REST, so the ledger can dedup across both.

    Settlement-status scope follows Contract #4 / §3.2:

    * a **WS** frame carries the whole-trade shadow status (starts ``MATCHED``),
      tagged :attr:`~mm_v2.domain.fill.StatusScope.LOGICAL_TRADE`;
    * a **REST** row is one settlement *bucket*, so its ``status`` is tagged
      :attr:`~mm_v2.domain.fill.StatusScope.BUCKET` — a single bucket must never
      be promoted to a logical-trade terminality claim. Logical terminality is
      folded across all buckets by
      :func:`~mm_v2.domain.fill.logical_status_from_buckets`.

    ``ws_side_convention`` keeps WS trade-side semantics configurable until an M0
    probe proves them (PLAN §8); REST maker fills carry their own explicit side.
    """
    is_rest = isinstance(trade, RestTradeEvent)
    status_scope = StatusScope.BUCKET if is_rest else StatusScope.LOGICAL_TRADE
    fills: list[LogicalFill] = []
    for maker in trade.maker_orders:
        # REST maker fills carry their own side; WS ones are interpreted per §8.
        if isinstance(maker, RestMakerOrderFill):
            side = maker.side
        else:
            side = _ws_maker_side(trade.side, ws_side_convention)
        fills.append(
            LogicalFill(
                trade_id=trade.trade_id,
                maker_order_id=maker.order_id,
                taker_order_id=trade.taker_order_id,
                asset_id=maker.asset_id,
                outcome=maker.outcome,
                side=side,
                price=maker.price,
                size=maker.matched_amount,
                match_time=trade.match_time,
                status=trade.status,
                status_scope=status_scope,
            )
        )
    return fills


def derive_settlement_buckets(trade: TradeEvent) -> list[SettlementBucket]:
    """Derive settlement buckets — only for REST trades (Contract #4).

    A WS trade has no bucket/transaction metadata, so it yields an empty list.
    The fill stays unconfirmed exposure until a REST record proves its buckets
    terminal.
    """
    if not isinstance(trade, RestTradeEvent):
        return []
    return [
        SettlementBucket(
            trade_id=trade.trade_id,
            bucket_index=trade.bucket_index,
            match_time=trade.match_time,
            transaction_hash=trade.transaction_hash,
            status=trade.status,
            status_scope=StatusScope.BUCKET,
        )
    ]
