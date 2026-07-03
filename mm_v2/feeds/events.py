"""Contract #1b — ``ParsedRecordedEvent`` typed union + the single decode
boundary (WS-A).

WS-A / WS-C / replay consume :data:`ParsedRecordedEvent`, never re-parsing
``raw_payload``. There is exactly one ``decode_recorded_event`` function; when
its parsing changes, bump ``PARSER_VERSION`` in :mod:`mm_v2.feeds.recorder`.

Field sets are verified against the Market / User WS docs (PLAN §10):

* ``MarketPriceChange`` has **no** top-level ``asset_id``; one message may carry
  BOTH YES and NO changes; ``size == 0`` means the level was removed; each
  change carries its own ``asset_id`` + ``hash`` that verifies THAT asset's book.
  The delta array arrives under ``price_changes`` on the live wire (``changes``
  kept as a fallback).
* User-channel WS frames carry **no** bucket/transaction metadata. Settlement
  buckets (``bucket_index`` / ``transaction_hash``) arrive only on the REST
  trades endpoint (``RestTradeEvent``) — the decoder must not fabricate them.
* All WS numeric fields arrive as JSON strings; the decoder normalizes them to
  ``Decimal`` (prices/sizes) or ``int`` (bps) here, so nothing downstream sees
  raw strings.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, NamedTuple

from mm_v2.domain.fill import SettlementStatus
from mm_v2.domain.order import Outcome, Side
from mm_v2.feeds import recorder
from mm_v2.feeds.recorder import RecordedEvent, SourceKind


# --- numeric normalization --------------------------------------------------
def to_decimal(value: Any) -> Decimal:
    """Normalize a wire value (JSON string / int / float) to ``Decimal``.

    Floats are routed through ``str`` so we never inherit binary-float drift on
    a price or size (these must stay tick-exact).
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # guard: bool is an int subclass
        raise TypeError(f"refusing to coerce bool to Decimal: {value!r}")
    if isinstance(value, (int, str)):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    raise TypeError(f"cannot normalize {value!r} ({type(value).__name__}) to Decimal")


def opt_decimal(value: Any) -> Decimal | None:
    """Like :func:`to_decimal` but passes ``None`` / empty string through."""
    if value is None or value == "":
        return None
    return to_decimal(value)


def to_int(value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError(f"refusing to coerce bool to int: {value!r}")
    return int(value)


def opt_int(value: Any) -> int | None:
    """Like :func:`to_int` but passes ``None`` / empty string through."""
    if value is None or value == "":
        return None
    return to_int(value)


# --- shared sub-records -----------------------------------------------------
class PriceLevel(NamedTuple):
    """One (price, size) level of an L2 book side."""

    price: Decimal
    size: Decimal


class PriceLevelChange(NamedTuple):
    """One per-asset delta inside a ``MarketPriceChange`` message.

    ``size == 0`` ⇒ the level was removed. ``hash`` verifies/updates THAT
    asset's book (not a market-wide hash).
    """

    asset_id: str
    side: Side
    price: Decimal
    size: Decimal
    hash: str | None
    best_bid: Decimal | None
    best_ask: Decimal | None

    @property
    def is_removal(self) -> bool:
        return self.size == 0


# --- Market channel ---------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MarketBookSnapshot:
    asset_id: str
    market: str
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]
    hash: str | None
    timestamp: int | None


@dataclass(frozen=True, slots=True)
class MarketPriceChange:
    market: str
    changes: tuple[PriceLevelChange, ...]
    timestamp: int | None


@dataclass(frozen=True, slots=True)
class MarketLastTrade:
    asset_id: str
    market: str
    price: Decimal
    side: Side
    size: Decimal
    fee_rate_bps: int | None
    timestamp: int | None


@dataclass(frozen=True, slots=True)
class TickSizeChange:
    asset_id: str
    market: str
    old_tick_size: Decimal
    new_tick_size: Decimal
    timestamp: int | None


@dataclass(frozen=True, slots=True)
class BestBidAsk:
    asset_id: str
    market: str
    best_bid: Decimal | None
    best_ask: Decimal | None
    timestamp: int | None


@dataclass(frozen=True, slots=True)
class MarketResolved:
    condition_id: str
    winning_outcome: Outcome | None
    timestamp: int | None


# --- User channel (WebSocket — no bucket/tx metadata) -----------------------
class UserOrderUpdateType(Enum):
    PLACEMENT = "PLACEMENT"
    UPDATE = "UPDATE"
    CANCELLATION = "CANCELLATION"


@dataclass(frozen=True, slots=True)
class WsMakerOrderFill:
    order_id: str
    matched_amount: Decimal
    owner: str
    asset_id: str
    outcome: Outcome
    price: Decimal


@dataclass(frozen=True, slots=True)
class UserOrderEvent:
    order_id: str
    asset_id: str
    market: str
    type: UserOrderUpdateType
    price: Decimal | None
    size: Decimal | None
    size_matched: Decimal
    status: str
    timestamp: int | None


@dataclass(frozen=True, slots=True)
class UserTradeWsEvent:
    trade_id: str
    taker_order_id: str
    asset_id: str
    market: str
    side: Side
    outcome: Outcome
    price: Decimal
    size: Decimal
    status: SettlementStatus
    maker_orders: tuple[WsMakerOrderFill, ...]
    match_time: str
    timestamp: int | None
    last_update: str | None = None


# --- REST trades endpoint (settlement/bucket metadata — Contract #4) --------
@dataclass(frozen=True, slots=True)
class RestMakerOrderFill:
    order_id: str
    matched_amount: Decimal
    owner: str
    maker_address: str
    asset_id: str
    outcome: Outcome
    price: Decimal
    fee_rate_bps: int | None
    side: Side


@dataclass(frozen=True, slots=True)
class RestTradeEvent:
    trade_id: str
    taker_order_id: str
    asset_id: str
    market: str
    side: Side
    outcome: Outcome
    price: Decimal
    size: Decimal
    status: SettlementStatus
    maker_orders: tuple[RestMakerOrderFill, ...]
    bucket_index: int
    transaction_hash: str | None
    match_time: str
    timestamp: int | None


# --- Recorder-internal ------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RestSnapshot:
    asset_id: str
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]
    hash: str | None
    snapshot_id: str | None
    server_ts: int | None


class SyntheticMarkerKind(Enum):
    RECONNECT = "RECONNECT"
    UNSYNCED = "UNSYNCED"
    GAP = "GAP"
    HEARTBEAT_MISS = "HEARTBEAT_MISS"


@dataclass(frozen=True, slots=True)
class SyntheticMarker:
    kind: SyntheticMarkerKind
    detail: str


ParsedRecordedEvent = (
    MarketBookSnapshot
    | MarketPriceChange
    | MarketLastTrade
    | TickSizeChange
    | BestBidAsk
    | MarketResolved
    | UserOrderEvent
    | UserTradeWsEvent
    | RestTradeEvent
    | RestSnapshot
    | SyntheticMarker
)


class DecodeError(ValueError):
    """Raised when a recorded event cannot be decoded into the typed union."""


# --- field parsers ----------------------------------------------------------
def _parse_side(value: Any) -> Side:
    token = str(value).strip().upper()
    if token in ("BUY", "BID", "B"):
        return Side.BUY
    if token in ("SELL", "ASK", "A", "S"):
        return Side.SELL
    raise DecodeError(f"unknown side: {value!r}")


def _parse_outcome(value: Any) -> Outcome:
    token = str(value).strip().upper()
    if token == "YES":
        return Outcome.YES
    if token == "NO":
        return Outcome.NO
    raise DecodeError(f"unknown outcome: {value!r}")


def _parse_settlement_status(value: Any) -> SettlementStatus:
    # The REST /data/trades endpoint reports protobuf-style names
    # (TRADE_STATUS_CONFIRMED); the User WS uses the bare form (CONFIRMED). Accept
    # both — dropping a documented prefix (exact wire form is M0-verifiable, §11).
    token = str(value).strip().upper()
    if token.startswith("TRADE_STATUS_"):
        token = token[len("TRADE_STATUS_") :]
    try:
        return SettlementStatus(token)
    except ValueError as exc:
        raise DecodeError(f"unknown settlement status: {value!r}") from exc


def _parse_levels(raw: Any) -> tuple[PriceLevel, ...]:
    return tuple(
        PriceLevel(price=to_decimal(lv["price"]), size=to_decimal(lv["size"]))
        for lv in (raw or [])
    )


def _book_sides(payload: Mapping[str, Any]) -> tuple[tuple[PriceLevel, ...], tuple[PriceLevel, ...]]:
    # Polymarket has used both bids/asks and buys/sells across channel versions.
    bids = _parse_levels(payload.get("bids", payload.get("buys")))
    asks = _parse_levels(payload.get("asks", payload.get("sells")))
    return bids, asks


def _ws_maker_orders(raw: Any) -> tuple[WsMakerOrderFill, ...]:
    return tuple(
        WsMakerOrderFill(
            order_id=str(m["order_id"]),
            matched_amount=to_decimal(m["matched_amount"]),
            owner=str(m["owner"]),
            asset_id=str(m["asset_id"]),
            outcome=_parse_outcome(m["outcome"]),
            price=to_decimal(m["price"]),
        )
        for m in (raw or [])
    )


def _rest_maker_orders(raw: Any) -> tuple[RestMakerOrderFill, ...]:
    return tuple(
        RestMakerOrderFill(
            order_id=str(m["order_id"]),
            matched_amount=to_decimal(m["matched_amount"]),
            owner=str(m["owner"]),
            maker_address=str(m["maker_address"]),
            asset_id=str(m["asset_id"]),
            outcome=_parse_outcome(m["outcome"]),
            price=to_decimal(m["price"]),
            fee_rate_bps=opt_int(m.get("fee_rate_bps")),
            side=_parse_side(m["side"]),
        )
        for m in (raw or [])
    )


# --- per-channel decoders ---------------------------------------------------
def _decode_market(event: RecordedEvent) -> ParsedRecordedEvent:
    p = event.raw_payload
    et = event.event_type
    if et == recorder.EVENT_BOOK:
        bids, asks = _book_sides(p)
        return MarketBookSnapshot(
            asset_id=str(p["asset_id"]),
            market=str(p.get("market", event.condition_id)),
            bids=bids,
            asks=asks,
            hash=p.get("hash"),
            timestamp=opt_int(p.get("timestamp")),
        )
    if et == recorder.EVENT_PRICE_CHANGE:
        changes = tuple(
            PriceLevelChange(
                asset_id=str(c["asset_id"]),  # per-change, no top-level asset_id
                side=_parse_side(c["side"]),
                price=to_decimal(c["price"]),
                size=to_decimal(c["size"]),
                hash=c.get("hash"),
                best_bid=opt_decimal(c.get("best_bid")),
                best_ask=opt_decimal(c.get("best_ask")),
            )
            # Live market WS carries the array under `price_changes`; keep
            # `changes` as a fallback (exact field is M0-verifiable — PLAN §11).
            for c in p.get("price_changes", p.get("changes", []))
        )
        return MarketPriceChange(
            market=str(p.get("market", event.condition_id)),
            changes=changes,
            timestamp=opt_int(p.get("timestamp")),
        )
    if et == recorder.EVENT_LAST_TRADE:
        return MarketLastTrade(
            asset_id=str(p["asset_id"]),
            market=str(p.get("market", event.condition_id)),
            price=to_decimal(p["price"]),
            side=_parse_side(p["side"]),
            size=to_decimal(p["size"]),
            fee_rate_bps=opt_int(p.get("fee_rate_bps")),
            timestamp=opt_int(p.get("timestamp")),
        )
    if et == recorder.EVENT_TICK_SIZE_CHANGE:
        return TickSizeChange(
            asset_id=str(p["asset_id"]),
            market=str(p.get("market", event.condition_id)),
            old_tick_size=to_decimal(p["old_tick_size"]),
            new_tick_size=to_decimal(p["new_tick_size"]),
            timestamp=opt_int(p.get("timestamp")),
        )
    if et == recorder.EVENT_BEST_BID_ASK:
        return BestBidAsk(
            asset_id=str(p["asset_id"]),
            market=str(p.get("market", event.condition_id)),
            best_bid=opt_decimal(p.get("best_bid")),
            best_ask=opt_decimal(p.get("best_ask")),
            timestamp=opt_int(p.get("timestamp")),
        )
    if et == recorder.EVENT_MARKET_RESOLVED:
        winner = p.get("winning_outcome")
        return MarketResolved(
            condition_id=str(p.get("condition_id", event.condition_id)),
            winning_outcome=_parse_outcome(winner) if winner else None,
            timestamp=opt_int(p.get("timestamp")),
        )
    raise DecodeError(f"unknown market event_type: {event.event_type!r}")


def _decode_user_order(event: RecordedEvent) -> UserOrderEvent:
    p = event.raw_payload
    try:
        update_type = UserOrderUpdateType(str(p["type"]).strip().upper())
    except (KeyError, ValueError) as exc:
        raise DecodeError(f"unknown user order type: {p.get('type')!r}") from exc
    return UserOrderEvent(
        order_id=str(p.get("order_id", p.get("id"))),
        asset_id=str(p["asset_id"]),
        market=str(p.get("market", event.condition_id)),
        type=update_type,
        price=opt_decimal(p.get("price")),
        size=opt_decimal(p.get("original_size", p.get("size"))),
        size_matched=to_decimal(p.get("size_matched", "0")),
        status=str(p.get("status", "")),
        timestamp=opt_int(p.get("timestamp")),
    )


def _decode_ws_trade(event: RecordedEvent) -> UserTradeWsEvent:
    p = event.raw_payload
    return UserTradeWsEvent(
        trade_id=str(p.get("trade_id", p.get("id"))),
        taker_order_id=str(p["taker_order_id"]),
        asset_id=str(p["asset_id"]),
        market=str(p.get("market", event.condition_id)),
        side=_parse_side(p["side"]),
        outcome=_parse_outcome(p["outcome"]),
        price=to_decimal(p["price"]),
        size=to_decimal(p["size"]),
        status=_parse_settlement_status(p["status"]),
        maker_orders=_ws_maker_orders(p.get("maker_orders")),
        match_time=str(p["match_time"]),
        timestamp=opt_int(p.get("timestamp")),
        last_update=(str(p["last_update"]) if p.get("last_update") else None),
    )


def _decode_rest_trade(event: RecordedEvent) -> RestTradeEvent:
    p = event.raw_payload
    return RestTradeEvent(
        trade_id=str(p.get("trade_id", p.get("id"))),
        taker_order_id=str(p["taker_order_id"]),
        asset_id=str(p["asset_id"]),
        market=str(p.get("market", event.condition_id)),
        side=_parse_side(p["side"]),
        outcome=_parse_outcome(p["outcome"]),
        price=to_decimal(p["price"]),
        size=to_decimal(p["size"]),
        status=_parse_settlement_status(p["status"]),
        maker_orders=_rest_maker_orders(p.get("maker_orders")),
        bucket_index=to_int(p["bucket_index"]),
        transaction_hash=(str(p["transaction_hash"]) if p.get("transaction_hash") else None),
        match_time=str(p["match_time"]),
        timestamp=opt_int(p.get("timestamp")),
    )


def _decode_rest_snapshot(event: RecordedEvent) -> RestSnapshot:
    p = event.raw_payload
    bids, asks = _book_sides(p)
    return RestSnapshot(
        asset_id=str(p["asset_id"]),
        bids=bids,
        asks=asks,
        hash=p.get("hash"),
        snapshot_id=(str(p["snapshot_id"]) if p.get("snapshot_id") else event.snapshot_id),
        server_ts=opt_int(p.get("server_ts", p.get("timestamp"))),
    )


def _decode_synthetic(event: RecordedEvent) -> SyntheticMarker:
    p = event.raw_payload
    try:
        kind = SyntheticMarkerKind(str(p["kind"]).strip().upper())
    except (KeyError, ValueError) as exc:
        raise DecodeError(f"unknown synthetic marker kind: {p.get('kind')!r}") from exc
    return SyntheticMarker(kind=kind, detail=str(p.get("detail", "")))


def decode_recorded_event(event: RecordedEvent) -> ParsedRecordedEvent:
    """The single sanctioned decode boundary (Contract #1b).

    Dispatches on ``(source_kind, event_type)`` and normalizes wire numerics to
    ``Decimal`` / ``int`` so nothing downstream re-parses ``raw_payload``.

    A trade is decoded as :class:`UserTradeWsEvent` from the User WS (no bucket
    metadata) and as :class:`RestTradeEvent` from a REST poll (with
    ``bucket_index`` / ``transaction_hash``) — see Contract #4. The decoder never
    fabricates bucket metadata for a WS frame.
    """
    try:
        if event.source_kind is SourceKind.MARKET_WS:
            return _decode_market(event)
        if event.source_kind is SourceKind.USER_WS:
            if event.event_type == recorder.EVENT_ORDER:
                return _decode_user_order(event)
            if event.event_type == recorder.EVENT_TRADE:
                return _decode_ws_trade(event)
            raise DecodeError(f"unknown user event_type: {event.event_type!r}")
        if event.source_kind is SourceKind.REST_SNAPSHOT:
            if event.event_type == recorder.EVENT_TRADE:
                return _decode_rest_trade(event)
            if event.event_type == recorder.EVENT_BOOK:
                return _decode_rest_snapshot(event)
            raise DecodeError(f"unknown REST event_type: {event.event_type!r}")
        if event.source_kind is SourceKind.SYNTHETIC_MARKER:
            return _decode_synthetic(event)
    except (KeyError, TypeError) as exc:
        raise DecodeError(
            f"malformed payload for {event.source_kind.value}/{event.event_type}: {exc}"
        ) from exc
    raise DecodeError(f"unhandled source_kind: {event.source_kind!r}")
