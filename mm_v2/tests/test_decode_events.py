"""Contract #1b decode-boundary tests (WS-A).

Covers the decode rules the PLAN calls out explicitly: numeric strings → Decimal,
``MarketPriceChange`` carries both YES & NO with no top-level asset_id and a
``size==0`` removal flag, and WS trades carry no bucket/tx metadata while REST
trades do.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from mm_v2.domain.fill import SettlementStatus
from mm_v2.domain.order import Outcome, Side
from mm_v2.feeds import events
from mm_v2.feeds.events import (
    BestBidAsk,
    DecodeError,
    MarketBookSnapshot,
    MarketLastTrade,
    MarketPriceChange,
    MarketResolved,
    RestSnapshot,
    RestTradeEvent,
    SyntheticMarker,
    SyntheticMarkerKind,
    TickSizeChange,
    UserOrderEvent,
    UserOrderUpdateType,
    UserTradeWsEvent,
    decode_recorded_event,
)
from mm_v2.feeds.recorder import RecordedEvent, SourceKind

CONDITION = "0xcondition"
YES_TOK = "yes-token"
NO_TOK = "no-token"


def make_event(
    source_kind: SourceKind,
    event_type: str,
    payload: dict[str, Any],
) -> RecordedEvent:
    return RecordedEvent(
        schema_version=1,
        recording_run_id="run-1",
        local_sequence=1,
        exchange_timestamp=1700000000000,
        local_receive_timestamp=1700000000.5,
        monotonic_timestamp=123.0,
        source_kind=source_kind,
        channel="market" if source_kind is SourceKind.MARKET_WS else "user",
        event_type=event_type,
        raw_payload=payload,
        condition_id=CONDITION,
    )


def test_decode_book_snapshot_normalizes_strings_to_decimal() -> None:
    rec = make_event(
        SourceKind.MARKET_WS,
        "book",
        {
            "asset_id": YES_TOK,
            "market": CONDITION,
            "bids": [{"price": "0.48", "size": "100"}, {"price": "0.47", "size": "250"}],
            "asks": [{"price": "0.52", "size": "200"}],
            "hash": "bookhash",
            "timestamp": "1700000000000",
        },
    )

    parsed = decode_recorded_event(rec)

    assert isinstance(parsed, MarketBookSnapshot)
    assert parsed.asset_id == YES_TOK
    assert parsed.bids[0].price == Decimal("0.48")
    assert parsed.bids[0].size == Decimal("100")
    assert isinstance(parsed.bids[0].price, Decimal)
    assert parsed.asks[0].price == Decimal("0.52")
    assert parsed.hash == "bookhash"
    assert parsed.timestamp == 1700000000000


def test_decode_price_change_carries_both_yes_and_no_with_removal_flag() -> None:
    rec = make_event(
        SourceKind.MARKET_WS,
        "price_change",
        {
            # NOTE: no top-level asset_id (Contract #1b)
            "market": CONDITION,
            "changes": [
                {
                    "asset_id": YES_TOK,
                    "side": "SELL",
                    "price": "0.52",
                    "size": "150",
                    "hash": "h-yes",
                    "best_bid": "0.48",
                    "best_ask": "0.52",
                },
                {
                    "asset_id": NO_TOK,
                    "side": "BUY",
                    "price": "0.49",
                    "size": "0",  # level removed
                    "hash": "h-no",
                    "best_bid": "0.47",
                    "best_ask": "0.51",
                },
            ],
            "timestamp": "1700000000001",
        },
    )

    parsed = decode_recorded_event(rec)

    assert isinstance(parsed, MarketPriceChange)
    assert len(parsed.changes) == 2
    assets = {c.asset_id for c in parsed.changes}
    assert assets == {YES_TOK, NO_TOK}

    yes_change = next(c for c in parsed.changes if c.asset_id == YES_TOK)
    no_change = next(c for c in parsed.changes if c.asset_id == NO_TOK)
    assert yes_change.side is Side.SELL
    assert yes_change.price == Decimal("0.52")
    assert yes_change.hash == "h-yes"  # per-change hash, not market-wide
    assert yes_change.is_removal is False
    assert no_change.is_removal is True  # size == 0
    assert no_change.best_ask == Decimal("0.51")


def test_decode_price_change_reads_price_changes_wire_field() -> None:
    # Live market WS price_change frames carry the array under `price_changes`;
    # the decoder must read that (not silently drop deltas), keeping `changes` as
    # a fallback. Dropping these would run replay/markout on stale post-snapshot
    # books.
    rec = make_event(
        SourceKind.MARKET_WS,
        "price_change",
        {
            "market": CONDITION,
            "price_changes": [
                {
                    "asset_id": YES_TOK,
                    "side": "SELL",
                    "price": "0.53",
                    "size": "120",
                    "hash": "h-yes",
                    "best_bid": "0.48",
                    "best_ask": "0.53",
                },
            ],
            "timestamp": "1700000000010",
        },
    )

    parsed = decode_recorded_event(rec)

    assert isinstance(parsed, MarketPriceChange)
    assert len(parsed.changes) == 1
    assert parsed.changes[0].asset_id == YES_TOK
    assert parsed.changes[0].price == Decimal("0.53")
    assert parsed.changes[0].size == Decimal("120")


def test_decode_last_trade() -> None:
    rec = make_event(
        SourceKind.MARKET_WS,
        "last_trade_price",
        {
            "asset_id": YES_TOK,
            "market": CONDITION,
            "price": "0.50",
            "side": "BUY",
            "size": "10",
            "fee_rate_bps": "0",
            "timestamp": "1700000000002",
        },
    )

    parsed = decode_recorded_event(rec)

    assert isinstance(parsed, MarketLastTrade)
    assert parsed.price == Decimal("0.50")
    assert parsed.side is Side.BUY
    assert parsed.fee_rate_bps == 0


def test_decode_tick_size_change() -> None:
    rec = make_event(
        SourceKind.MARKET_WS,
        "tick_size_change",
        {
            "asset_id": YES_TOK,
            "market": CONDITION,
            "old_tick_size": "0.01",
            "new_tick_size": "0.001",
            "timestamp": "1700000000003",
        },
    )

    parsed = decode_recorded_event(rec)

    assert isinstance(parsed, TickSizeChange)
    assert parsed.old_tick_size == Decimal("0.01")
    assert parsed.new_tick_size == Decimal("0.001")


def test_decode_best_bid_ask_allows_missing_side() -> None:
    rec = make_event(
        SourceKind.MARKET_WS,
        "best_bid_ask",
        {
            "asset_id": YES_TOK,
            "market": CONDITION,
            "best_bid": "0.48",
            "best_ask": "",  # empty ⇒ None
            "timestamp": "1700000000004",
        },
    )

    parsed = decode_recorded_event(rec)

    assert isinstance(parsed, BestBidAsk)
    assert parsed.best_bid == Decimal("0.48")
    assert parsed.best_ask is None


def test_decode_user_order_event() -> None:
    rec = make_event(
        SourceKind.USER_WS,
        "order",
        {
            "order_id": "ord-1",
            "asset_id": YES_TOK,
            "market": CONDITION,
            "type": "PLACEMENT",
            "price": "0.52",
            "original_size": "100",
            "size_matched": "0",
            "status": "LIVE",
            "timestamp": "1700000000005",
        },
    )

    parsed = decode_recorded_event(rec)

    assert isinstance(parsed, UserOrderEvent)
    assert parsed.order_id == "ord-1"
    assert parsed.type is UserOrderUpdateType.PLACEMENT
    assert parsed.price == Decimal("0.52")
    assert parsed.size == Decimal("100")
    assert parsed.size_matched == Decimal("0")


def test_decode_ws_trade_has_no_bucket_metadata() -> None:
    rec = make_event(
        SourceKind.USER_WS,
        "trade",
        {
            "trade_id": "trade-1",
            "taker_order_id": "taker-1",
            "asset_id": YES_TOK,
            "market": CONDITION,
            "side": "BUY",
            "outcome": "YES",
            "price": "0.52",
            "size": "100",
            "status": "MATCHED",
            "match_time": "1700000000",
            "maker_orders": [
                {
                    "order_id": "maker-A",
                    "matched_amount": "60",
                    "owner": "0xowner",
                    "asset_id": YES_TOK,
                    "outcome": "YES",
                    "price": "0.52",
                },
                {
                    "order_id": "maker-B",
                    "matched_amount": "40",
                    "owner": "0xowner",
                    "asset_id": YES_TOK,
                    "outcome": "YES",
                    "price": "0.52",
                },
            ],
            "timestamp": "1700000000006",
        },
    )

    parsed = decode_recorded_event(rec)

    assert isinstance(parsed, UserTradeWsEvent)
    assert parsed.status is SettlementStatus.MATCHED
    assert parsed.match_time == "1700000000"
    assert len(parsed.maker_orders) == 2
    assert parsed.maker_orders[0].matched_amount == Decimal("60")
    # A WS frame carries no bucket/tx metadata, and the decoder must not invent it.
    assert not hasattr(parsed, "bucket_index")
    assert not hasattr(parsed, "transaction_hash")


def test_decode_rest_trade_has_bucket_metadata() -> None:
    rec = make_event(
        SourceKind.REST_SNAPSHOT,
        "trade",
        {
            "trade_id": "trade-1",
            "taker_order_id": "taker-1",
            "asset_id": YES_TOK,
            "market": CONDITION,
            "side": "BUY",
            "outcome": "YES",
            "price": "0.52",
            "size": "100",
            "status": "CONFIRMED",
            "bucket_index": "0",
            "transaction_hash": "0xdeadbeef",
            "match_time": "1700000000",
            "maker_orders": [
                {
                    "order_id": "maker-A",
                    "matched_amount": "60",
                    "owner": "0xowner",
                    "maker_address": "0xmaker",
                    "asset_id": YES_TOK,
                    "outcome": "YES",
                    "price": "0.52",
                    "fee_rate_bps": "0",
                    "side": "SELL",
                }
            ],
            "timestamp": "1700000000007",
        },
    )

    parsed = decode_recorded_event(rec)

    assert isinstance(parsed, RestTradeEvent)
    assert parsed.status is SettlementStatus.CONFIRMED
    assert parsed.bucket_index == 0
    assert parsed.transaction_hash == "0xdeadbeef"
    assert parsed.maker_orders[0].maker_address == "0xmaker"
    assert parsed.maker_orders[0].side is Side.SELL


def test_decode_market_resolved() -> None:
    rec = make_event(
        SourceKind.MARKET_WS,
        "market_resolved",
        {
            "condition_id": CONDITION,
            "winning_outcome": "YES",
            "timestamp": "1700000000008",
        },
    )

    parsed = decode_recorded_event(rec)

    assert isinstance(parsed, MarketResolved)
    assert parsed.condition_id == CONDITION
    assert parsed.winning_outcome is Outcome.YES


def test_decode_market_resolved_falls_back_to_market_for_condition_id() -> None:
    # Real market_resolved frames carry the condition id in `market` and may omit
    # `condition_id`; the decoder must use `market` (not fall straight through to
    # the envelope, which can be unset → the literal "None").
    rec = make_event(
        SourceKind.MARKET_WS,
        "market_resolved",
        {"market": "0xcond-from-market", "winning_outcome": "NO"},
    )

    parsed = decode_recorded_event(rec)

    assert isinstance(parsed, MarketResolved)
    assert parsed.condition_id == "0xcond-from-market"
    assert parsed.winning_outcome is Outcome.NO


def test_decode_market_resolved_allows_unknown_winner() -> None:
    # Resolution can arrive before the winning outcome is known/populated.
    rec = make_event(SourceKind.MARKET_WS, "market_resolved", {"condition_id": CONDITION})

    parsed = decode_recorded_event(rec)

    assert isinstance(parsed, MarketResolved)
    assert parsed.winning_outcome is None


def test_decode_rest_snapshot_book() -> None:
    rec = make_event(
        SourceKind.REST_SNAPSHOT,
        "book",
        {
            "asset_id": YES_TOK,
            "bids": [{"price": "0.48", "size": "100"}],
            "asks": [{"price": "0.52", "size": "200"}],
            "hash": "snap-hash",
            "snapshot_id": "snap-1",
            "server_ts": "1700000000009",
        },
    )

    parsed = decode_recorded_event(rec)

    assert isinstance(parsed, RestSnapshot)
    assert parsed.asset_id == YES_TOK
    assert parsed.bids[0].price == Decimal("0.48")
    assert parsed.asks[0].size == Decimal("200")
    assert parsed.snapshot_id == "snap-1"
    assert parsed.server_ts == 1700000000009


def test_decode_synthetic_marker() -> None:
    rec = make_event(
        SourceKind.SYNTHETIC_MARKER,
        "marker",
        {"kind": "RECONNECT", "detail": "socket dropped"},
    )

    parsed = decode_recorded_event(rec)

    assert isinstance(parsed, SyntheticMarker)
    assert parsed.kind is SyntheticMarkerKind.RECONNECT
    assert parsed.detail == "socket dropped"


def test_decode_synthetic_marker_unknown_kind_raises() -> None:
    rec = make_event(SourceKind.SYNTHETIC_MARKER, "marker", {"kind": "NONSENSE"})
    with pytest.raises(DecodeError):
        decode_recorded_event(rec)


def test_decode_rest_trade_accepts_prefixed_status() -> None:
    # The CLOB /data/trades endpoint reports protobuf-style status names, e.g.
    # TRADE_STATUS_CONFIRMED. The decoder must accept them — else no settlement
    # bucket is produced and WS fills never reconcile terminal.
    rec = make_event(
        SourceKind.REST_SNAPSHOT,
        "trade",
        {
            "trade_id": "trade-1",
            "taker_order_id": "taker-1",
            "asset_id": YES_TOK,
            "market": CONDITION,
            "side": "BUY",
            "outcome": "YES",
            "price": "0.52",
            "size": "100",
            "status": "TRADE_STATUS_CONFIRMED",
            "bucket_index": "0",
            "transaction_hash": "0xdeadbeef",
            "match_time": "1700000000",
            "maker_orders": [
                {
                    "order_id": "maker-A",
                    "matched_amount": "100",
                    "owner": "0xowner",
                    "maker_address": "0xmaker",
                    "asset_id": YES_TOK,
                    "outcome": "YES",
                    "price": "0.52",
                    "fee_rate_bps": "0",
                    "side": "SELL",
                }
            ],
        },
    )

    parsed = decode_recorded_event(rec)

    assert isinstance(parsed, RestTradeEvent)
    assert parsed.status is SettlementStatus.CONFIRMED


def test_decode_unknown_event_type_raises_decode_error() -> None:
    rec = make_event(SourceKind.MARKET_WS, "nonsense_event", {"market": CONDITION})
    with pytest.raises(DecodeError):
        decode_recorded_event(rec)


def test_to_decimal_rejects_bool() -> None:
    with pytest.raises(TypeError):
        events.to_decimal(True)
