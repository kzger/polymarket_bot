"""Contract #1 — recorded event envelope (WS-A).

Everything downstream (book builder, shadow engine, replay) reads this envelope.
``raw_payload`` is retained verbatim, but downstream MUST NOT rely on ad hoc
parsing of it — the only sanctioned decode is
:func:`mm_v2.feeds.events.decode_recorded_event` (Contract #1b).

Replay ordering key = ``(recording_run_id, local_sequence)``. The Market WS
provides a ``hash`` but **no** official monotonic sequence number, so ordering
is assigned locally at ingest (``local_sequence``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

# Bump on any envelope field change (Contract #1).
SCHEMA_VERSION = 1
# Bump whenever decode_recorded_event's parsing changes (Contract #1 / #1b).
# v2: RestTradeEvent gained `trader_side` (top-level taker-fill capture).
PARSER_VERSION = 2


class SourceKind(Enum):
    """Where a recorded event originated.

    Note: ``REST_SNAPSHOT`` covers any REST-polled record. A REST *trades*-
    endpoint record (carrying Contract #4 bucket/tx metadata) is recorded with
    ``source_kind=REST_SNAPSHOT`` and ``event_type='trade'``; the decode
    boundary distinguishes it from a WS trade by source + event type. (See the
    interpretation note in PLAN §11.)
    """

    MARKET_WS = "market_ws"
    USER_WS = "user_ws"
    REST_SNAPSHOT = "rest_snapshot"
    SYNTHETIC_MARKER = "synthetic_marker"


class IngestionStatus(Enum):
    """Per-event ingest health. ``UNSYNCED`` / ``GAP`` are excluded from markout
    statistics (PLAN §7, §10)."""

    OK = "OK"
    STALE = "STALE"
    UNSYNCED = "UNSYNCED"
    GAP = "GAP"


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    """The frozen recorded-event envelope (Contract #1).

    Timestamps: ``exchange_timestamp`` is the venue-provided epoch (ms, may be
    absent); ``local_receive_timestamp`` is wall-clock ``time.time()``;
    ``monotonic_timestamp`` is ``time.monotonic()`` for ordering/latency that is
    immune to clock steps.
    """

    schema_version: int
    recording_run_id: str
    local_sequence: int  # monotonic per run, assigned at ingest — THE replay key
    exchange_timestamp: int | None
    local_receive_timestamp: float
    monotonic_timestamp: float
    source_kind: SourceKind
    channel: str
    event_type: str
    raw_payload: Mapping[str, Any]
    parser_version: int = PARSER_VERSION
    condition_id: str | None = None
    asset_id: str | None = None  # absent for market price_change / synthetic markers
    book_hash: str | None = None  # Market WS `hash` when present
    snapshot_id: str | None = None  # links a REST snapshot to the deltas it verifies
    ingestion_status: IngestionStatus = IngestionStatus.OK
    connection_id: str | None = None
    reconnect_marker: bool = False

    def __post_init__(self) -> None:
        # The replay key must be sortable; guard the invariant cheaply.
        if self.local_sequence < 0:
            raise ValueError("local_sequence must be non-negative (replay order key)")


# Event-type discriminators used by the decode boundary (Contract #1b).
# Market channel
EVENT_BOOK = "book"
EVENT_PRICE_CHANGE = "price_change"
EVENT_LAST_TRADE = "last_trade_price"
EVENT_TICK_SIZE_CHANGE = "tick_size_change"
EVENT_BEST_BID_ASK = "best_bid_ask"
EVENT_MARKET_RESOLVED = "market_resolved"
# User channel
EVENT_ORDER = "order"
EVENT_TRADE = "trade"
# Synthetic
EVENT_MARKER = "marker"


def next_sequence(counter: int) -> int:
    """Return the next ``local_sequence`` value. Trivial, but centralizes the
    'monotonic, assigned at ingest' rule so the recorder never reuses a key."""
    return counter + 1
