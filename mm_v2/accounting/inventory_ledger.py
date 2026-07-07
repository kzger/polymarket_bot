"""Immutable fill ledger → inventory bridge (WS-C) — Contract #4.

Folds Contract #1b parsed trade events into :class:`~mm_v2.domain.fill.Fill`
records. Inventory is *derived* from the immutable ledger, never a mutated
running total (PLAN §3.2).

This module is the one place allowed to depend on BOTH feeds and domain. The
two derive functions enforce Contract #4 at the boundary:

* ``derive_logical_fills`` — one :class:`LogicalFill` per ``maker_orders[]``
  entry when the user is the maker, keyed ``(trade_id, maker_order_id)``; ONE
  top-level fill keyed ``(trade_id, taker_order_id)`` when the user is the
  taker (REST ``trader_side == "TAKER"``, or WS ``taker_order_id`` in the
  caller's own-order-id set). Identity is stable across the WS frame and the
  later REST record for the same trade.
* ``derive_settlement_buckets`` — a settlement bucket exists ONLY when REST/
  on-chain metadata is present. A WS frame yields none; we never fabricate a
  ``bucket_index`` / ``transaction_hash`` the wire did not carry.
"""

from __future__ import annotations

from collections.abc import Container

from mm_v2.domain.fill import (
    LogicalFill,
    SettlementBucket,
    StatusScope,
)
from mm_v2.domain.order import Side, TradeSideConvention
from mm_v2.feeds.events import RestMakerOrderFill, RestTradeEvent, UserTradeWsEvent

type TradeEvent = UserTradeWsEvent | RestTradeEvent


class UnattributableRestFillError(ValueError):
    """A REST trade row has empty ``maker_orders`` but is not a confirmable TAKER
    fill (``trader_side`` absent or not ``TAKER``), so the user's fill cannot be
    attributed. Raised **loudly** — never a silent drop of a settled fill.

    The reconciler (WS-D) MUST catch this **per REST row**, emit a marker /
    diagnostic, and continue the rest of the poll — one bad row must not abort
    reconciliation. Needs M0 ``/data/trades`` wire verification (PLAN §11).
    """


class UnattributableWsFillError(ValueError):
    """A User WS trade matched NOTHING in the caller-supplied own-order-id set —
    neither ``taker_order_id`` nor any ``maker_orders`` entry is ours — so the
    user's fill cannot be attributed. Raised **loudly**: silence would hide
    either stale state (e.g. a frame replayed after reconnect) or an
    identity-tracking bug.

    The live handler (WS-D) MUST catch this **per event**, emit a marker /
    diagnostic, and continue the stream — one unattributable frame must not
    abort ingestion.
    """


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


def _ws_taker_side(taker_side: Side, convention: TradeSideConvention) -> Side:
    """Interpret a WS trade's ``side`` into OUR taker fill side (PLAN §8).

    Mirror of :func:`_ws_maker_side` — the side convention stays configurable on
    the taker path too, never hard-coded while §8 is unproven.
    """
    if convention is TradeSideConvention.TAKER_SIDE:
        return taker_side
    return _opposite_side(taker_side)


def _taker_fill(
    trade: TradeEvent, *, status_scope: StatusScope, side: Side
) -> LogicalFill:
    """Synthesize the user's fill from a taker trade's top-level fields.

    When the user is the TAKER the ``maker_orders`` are the COUNTERPARTIES, so
    our fill is the top-level row, keyed ``(trade_id, taker_order_id)`` per
    Contract #4 — identical for the WS frame and the REST row, so the ledger
    dedups across both. Scope is BUCKET for a REST row, LOGICAL_TRADE for a WS
    frame (which carries no bucket metadata).
    """
    return LogicalFill(
        trade_id=trade.trade_id,
        maker_order_id=trade.taker_order_id,  # Contract #4 generic order_id
        taker_order_id=trade.taker_order_id,
        asset_id=trade.asset_id,
        outcome=trade.outcome,
        side=side,
        price=trade.price,
        size=trade.size,
        match_time=trade.match_time,
        status=trade.status,
        status_scope=status_scope,
    )


def derive_logical_fills(
    trade: TradeEvent,
    *,
    ws_side_convention: TradeSideConvention = TradeSideConvention.TAKER_SIDE,
    our_order_ids: Container[str] | None = None,
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

    **REST top-level taker fills (Contract #4).** When a ``/data/trades`` row has
    ``trader_side == "TAKER"`` the ``maker_orders`` are the COUNTERPARTIES, not
    ours — regardless of whether that list is empty or populated — so our single
    fill is synthesized from the top-level fields, keyed ``(trade_id,
    taker_order_id)``, and the maker loop is skipped. An empty-``maker_orders`` REST
    row that is NOT a confirmed TAKER raises :class:`UnattributableRestFillError`
    (never a silent drop). For a given trade the user is maker **XOR** taker, so a
    taker-keyed fill and per-maker fills never coexist — no double count.

    **WS top-level taker fills (Contract #4).** A WS frame carries no
    ``trader_side``, so taker-ness is detected against the caller-supplied
    ``our_order_ids`` (own exchange order ids, e.g. from placement acks /
    ``UserOrderEvent``s): if ``taker_order_id`` is ours, we ARE the taker
    (deterministic) — one top-level fill keyed ``(trade_id, taker_order_id)``,
    ``LOGICAL_TRADE``-scoped (no buckets; stays unconfirmed until REST buckets
    prove terminality). Otherwise the maker loop is **filtered** to our own
    ``maker_orders`` entries (the channel may carry other makers' orders). If
    the set is provided and NOTHING matches, :class:`UnattributableWsFillError`
    is raised loudly. ``our_order_ids=None`` (default) preserves the
    undiscriminated legacy behavior: every maker entry is booked.
    """
    if isinstance(trade, RestTradeEvent) and trade.trader_side == "TAKER":
        return [_taker_fill(trade, status_scope=StatusScope.BUCKET, side=trade.side)]

    is_rest = isinstance(trade, RestTradeEvent)
    maker_orders = trade.maker_orders
    if not is_rest and our_order_ids is not None:
        if trade.taker_order_id in our_order_ids:
            return [
                _taker_fill(
                    trade,
                    status_scope=StatusScope.LOGICAL_TRADE,
                    side=_ws_taker_side(trade.side, ws_side_convention),
                )
            ]
        maker_orders = tuple(
            m for m in trade.maker_orders if m.order_id in our_order_ids
        )
        if not maker_orders:
            raise UnattributableWsFillError(
                f"WS trade {trade.trade_id!r}: neither taker_order_id "
                f"{trade.taker_order_id!r} nor any maker_orders entry is in "
                f"our_order_ids; cannot attribute the user fill"
            )

    status_scope = StatusScope.BUCKET if is_rest else StatusScope.LOGICAL_TRADE
    fills: list[LogicalFill] = []
    for maker in maker_orders:
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

    if isinstance(trade, RestTradeEvent) and not trade.maker_orders:
        # Empty maker_orders and not a confirmed TAKER (that returned above): the
        # user's fill cannot be attributed → raise loudly, never a silent drop.
        raise UnattributableRestFillError(
            f"REST trade {trade.trade_id!r} has empty maker_orders and "
            f"trader_side={trade.trader_side!r} (not TAKER); cannot attribute "
            f"the user fill"
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
