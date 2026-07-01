"""Contract #4 settlement-identity tests (WS-A decode → WS-C ledger bridge).

The same logical trade appears first on the User WS (no bucket/tx metadata) and
later on the REST trades endpoint (with ``bucket_index`` / ``transaction_hash``).
We assert that:

* the logical-fill key ``(trade_id, maker_order_id)`` is identical across the WS
  and REST records (identity is stable — the ledger dedups on it);
* a WS frame yields NO settlement buckets (the decoder/bridge must not fabricate
  them), while the REST record yields a bucket keyed by
  ``(trade_id, bucket_index, transaction_hash)``;
* the two records reconcile by ``match_time``;
* WS fills are unconfirmed exposure; the REST record can carry a terminal status.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from mm_v2.accounting.inventory_ledger import (
    derive_logical_fills,
    derive_settlement_buckets,
)
from mm_v2.domain.fill import (
    SettlementStatus,
    StatusScope,
    aggregate_logical_status,
    fill_dedup_key,
    logical_fill_key,
    logical_status_from_buckets,
    settlement_bucket_key,
)
from mm_v2.domain.order import Outcome, Side, TradeSideConvention
from mm_v2.feeds.events import RestTradeEvent, UserTradeWsEvent, decode_recorded_event
from mm_v2.feeds.recorder import RecordedEvent, SourceKind

TRADE_ID = "trade-77"
TAKER = "taker-1"
MAKER_A = "maker-A"
MAKER_B = "maker-B"
MATCH_TIME = "1700000000"
YES_TOK = "yes-token"
COND = "0xcond"


def _rec(source_kind: SourceKind, payload: dict[str, Any]) -> RecordedEvent:
    return RecordedEvent(
        schema_version=1,
        recording_run_id="run-1",
        local_sequence=1,
        exchange_timestamp=1700000000000,
        local_receive_timestamp=1700000000.5,
        monotonic_timestamp=1.0,
        source_kind=source_kind,
        channel="user" if source_kind is SourceKind.USER_WS else "rest",
        event_type="trade",
        raw_payload=payload,
        condition_id=COND,
    )


def _ws_trade() -> UserTradeWsEvent:
    payload = {
        "trade_id": TRADE_ID,
        "taker_order_id": TAKER,
        "asset_id": YES_TOK,
        "market": COND,
        "side": "BUY",
        "outcome": "YES",
        "price": "0.52",
        "size": "100",
        "status": "MATCHED",
        "match_time": MATCH_TIME,
        "maker_orders": [
            {"order_id": MAKER_A, "matched_amount": "60", "owner": "0xus",
             "asset_id": YES_TOK, "outcome": "YES", "price": "0.52"},
            {"order_id": MAKER_B, "matched_amount": "40", "owner": "0xus",
             "asset_id": YES_TOK, "outcome": "YES", "price": "0.52"},
        ],
    }
    parsed = decode_recorded_event(_rec(SourceKind.USER_WS, payload))
    assert isinstance(parsed, UserTradeWsEvent)
    return parsed


def _rest_trade(bucket_index: str = "0", status: str = "CONFIRMED") -> RestTradeEvent:
    payload = {
        "trade_id": TRADE_ID,
        "taker_order_id": TAKER,
        "asset_id": YES_TOK,
        "market": COND,
        "side": "BUY",
        "outcome": "YES",
        "price": "0.52",
        "size": "100",
        "status": status,
        "bucket_index": bucket_index,
        "transaction_hash": "0xabc",
        "match_time": MATCH_TIME,
        "maker_orders": [
            {"order_id": MAKER_A, "matched_amount": "60", "owner": "0xus",
             "maker_address": "0xus", "asset_id": YES_TOK, "outcome": "YES",
             "price": "0.52", "fee_rate_bps": "0", "side": "SELL"},
            {"order_id": MAKER_B, "matched_amount": "40", "owner": "0xus",
             "maker_address": "0xus", "asset_id": YES_TOK, "outcome": "YES",
             "price": "0.52", "fee_rate_bps": "0", "side": "SELL"},
        ],
    }
    parsed = decode_recorded_event(_rec(SourceKind.REST_SNAPSHOT, payload))
    assert isinstance(parsed, RestTradeEvent)
    return parsed


def test_logical_fill_keys_match_across_ws_and_rest() -> None:
    ws_fills = derive_logical_fills(_ws_trade())
    rest_fills = derive_logical_fills(_rest_trade())

    ws_keys = {f.key for f in ws_fills}
    rest_keys = {f.key for f in rest_fills}

    assert ws_keys == rest_keys
    assert ws_keys == {
        logical_fill_key(TRADE_ID, MAKER_A),
        logical_fill_key(TRADE_ID, MAKER_B),
    }


def test_one_logical_fill_per_maker_order_with_amounts() -> None:
    ws_fills = {f.maker_order_id: f for f in derive_logical_fills(_ws_trade())}
    assert ws_fills[MAKER_A].size == Decimal("60")
    assert ws_fills[MAKER_B].size == Decimal("40")
    assert ws_fills[MAKER_A].price == Decimal("0.52")
    assert ws_fills[MAKER_A].outcome is Outcome.YES
    # maker side is the opposite of the taker BUY (default TAKER_SIDE convention, §8)
    assert ws_fills[MAKER_A].side is Side.SELL


def test_ws_trade_yields_no_settlement_buckets() -> None:
    # A WS frame has no bucket/tx metadata; the bridge must NOT invent any.
    assert derive_settlement_buckets(_ws_trade()) == []


def test_rest_trade_yields_a_keyed_settlement_bucket() -> None:
    buckets = derive_settlement_buckets(_rest_trade(bucket_index="2"))
    assert len(buckets) == 1
    bucket = buckets[0]
    assert bucket.key == settlement_bucket_key(TRADE_ID, 2, "0xabc")
    assert bucket.status_scope is StatusScope.BUCKET


def test_ws_and_rest_reconcile_by_match_time() -> None:
    ws_fills = derive_logical_fills(_ws_trade())
    rest_fills = derive_logical_fills(_rest_trade())
    assert {f.match_time for f in ws_fills} == {MATCH_TIME}
    assert {f.match_time for f in rest_fills} == {MATCH_TIME}


def test_ws_fills_are_logical_scope_and_unconfirmed() -> None:
    ws_fills = derive_logical_fills(_ws_trade())
    assert all(f.status is SettlementStatus.MATCHED for f in ws_fills)
    assert all(f.status_scope is StatusScope.LOGICAL_TRADE for f in ws_fills)
    assert all(f.status.is_unconfirmed_exposure for f in ws_fills)


def test_rest_fill_status_is_bucket_scoped_not_logical_terminal() -> None:
    # A single REST row is ONE settlement bucket; its CONFIRMED must NOT be
    # promoted to a logical-trade terminality claim (§3.2: no early promote,
    # a logical trade is terminal only once ALL its buckets are terminal).
    rest_fills = derive_logical_fills(_rest_trade(status="CONFIRMED"))
    assert all(f.status is SettlementStatus.CONFIRMED for f in rest_fills)
    assert all(f.status_scope is StatusScope.BUCKET for f in rest_fills)


def test_logical_status_not_terminal_until_all_buckets_confirmed() -> None:
    # Trade split across two on-chain buckets: one CONFIRMED, one still RETRYING.
    buckets = derive_settlement_buckets(
        _rest_trade(bucket_index="0", status="CONFIRMED")
    ) + derive_settlement_buckets(_rest_trade(bucket_index="1", status="RETRYING"))
    logical = logical_status_from_buckets(buckets)
    assert logical is SettlementStatus.RETRYING
    assert not logical.is_terminal


def test_logical_status_confirmed_only_when_all_buckets_confirmed() -> None:
    buckets = derive_settlement_buckets(
        _rest_trade(bucket_index="0", status="CONFIRMED")
    ) + derive_settlement_buckets(_rest_trade(bucket_index="1", status="CONFIRMED"))
    logical = logical_status_from_buckets(buckets)
    assert logical is SettlementStatus.CONFIRMED
    assert logical.is_terminal


def test_logical_status_failed_if_any_bucket_failed() -> None:
    buckets = derive_settlement_buckets(
        _rest_trade(bucket_index="0", status="CONFIRMED")
    ) + derive_settlement_buckets(_rest_trade(bucket_index="1", status="FAILED"))
    logical = logical_status_from_buckets(buckets)
    assert logical is SettlementStatus.FAILED
    assert logical.is_terminal


def test_logical_status_reports_least_settled_when_pending() -> None:
    buckets = derive_settlement_buckets(
        _rest_trade(bucket_index="0", status="CONFIRMED")
    ) + derive_settlement_buckets(_rest_trade(bucket_index="1", status="MINED"))
    assert logical_status_from_buckets(buckets) is SettlementStatus.MINED


def test_logical_status_retrying_not_failed_when_bucket_still_open() -> None:
    # §3.2: a FAILED bucket alongside a still-open (non-terminal) bucket must NOT
    # promote the whole logical trade to terminal FAILED — that would be a
    # partial rollback at the wrong granularity. Surface non-terminal RETRYING so
    # the age-based reconcile/breaker runs while the open bucket resolves.
    buckets = derive_settlement_buckets(
        _rest_trade(bucket_index="0", status="FAILED")
    ) + derive_settlement_buckets(_rest_trade(bucket_index="1", status="MINED"))
    logical = logical_status_from_buckets(buckets)
    assert logical is SettlementStatus.RETRYING
    assert not logical.is_terminal


def test_logical_status_retrying_when_failed_and_retrying_buckets_mixed() -> None:
    # A FAILED and a RETRYING bucket, not terminal across ALL buckets: hold as
    # non-terminal RETRYING (never a terminal status while a bucket is open).
    buckets = derive_settlement_buckets(
        _rest_trade(bucket_index="0", status="FAILED")
    ) + derive_settlement_buckets(_rest_trade(bucket_index="1", status="RETRYING"))
    logical = logical_status_from_buckets(buckets)
    assert logical is SettlementStatus.RETRYING
    assert not logical.is_terminal


def test_aggregate_logical_status_precedence_table() -> None:
    # Full §3.2 precedence oracle: FAILED/CONFIRMED are only reported terminal
    # when ALL buckets are terminal; any open bucket alongside a FAILED/RETRYING
    # bucket surfaces non-terminal RETRYING.
    S = SettlementStatus
    cases: list[tuple[list[SettlementStatus], SettlementStatus]] = [
        ([], S.MATCHED),
        ([S.CONFIRMED, S.CONFIRMED], S.CONFIRMED),
        ([S.CONFIRMED, S.FAILED], S.FAILED),  # all terminal
        ([S.FAILED, S.FAILED], S.FAILED),
        ([S.CONFIRMED, S.MINED], S.MINED),
        ([S.CONFIRMED, S.MATCHED], S.MATCHED),
        ([S.CONFIRMED, S.RETRYING], S.RETRYING),
        ([S.FAILED, S.MINED], S.RETRYING),  # NEW — was FAILED
        ([S.FAILED, S.RETRYING], S.RETRYING),  # NEW
        ([S.MINED, S.MATCHED], S.MATCHED),
    ]
    for statuses, expected in cases:
        assert aggregate_logical_status(statuses) is expected, statuses


def test_ws_maker_side_convention_is_configurable() -> None:
    # §8: WS trade-side semantics are unproven; the maker-side interpretation
    # must stay a caller knob until an M0 controlled probe freezes it.
    default_fills = derive_logical_fills(_ws_trade())
    assert all(f.side is Side.SELL for f in default_fills)  # taker BUY → maker SELL

    flipped = derive_logical_fills(
        _ws_trade(), ws_side_convention=TradeSideConvention.MAKER_SIDE
    )
    assert all(f.side is Side.BUY for f in flipped)  # side read as the maker's own


def test_fill_dedup_key_is_stable_per_trade_maker_and_cumulative_size() -> None:
    fill = derive_logical_fills(_ws_trade())[0]
    key = fill_dedup_key(fill.trade_id, fill.maker_order_id, fill.size)
    assert key == (TRADE_ID, MAKER_A, Decimal("60"))
