"""Contract #2 — ``ExchangePort`` interface + typed request/result shapes.

Domain / strategy / risk depend only on these **typed** shapes (not on bare
method names or a concrete SDK), so the live adapter (WS-D), the WS-B risk layer
and a fake-port test double all model accepted / delayed / duplicate / timeout
identically.

Key invariants frozen by the PLAN (§10):

* A timeout / lost response MUST surface as ``SubmitStatus.UNKNOWN`` — never an
  exception only (the order may actually be live; see §4.4 lifecycle).
* Requests are split *by intent*: ``PassivePostOnlyOrderRequest`` is the only
  type v1 strategy emits; ``AggressiveOrderRequest`` is for M0 probes only.
* Post-only result invariant: a passive request must come back
  ``insert_status='live'`` OR ``REJECTED(error_code=post_only_cross_reject)``.
  ``insert_status ∈ {matched, delayed, unmatched}`` on a post-only order is a
  conformance failure → protocol breaker (handled in the TDD step below).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from mm_v2.domain.order import POST_ONLY_ORDER_TYPES, OrderType, Side
from mm_v2.feeds.events import PriceLevel
from mm_v2.feeds.recorder import RecordedEvent


# --- enums ------------------------------------------------------------------
class SubmitStatus(Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"  # lost response / timeout — never assume failure


class InsertStatus(Enum):
    """Matching-engine order insert status (verified vs CLOB V2 docs)."""

    MATCHED = "matched"
    LIVE = "live"
    DELAYED = "delayed"  # per-market taker delay; uncancelable while pending
    UNMATCHED = "unmatched"


class RestrictedMode(Enum):
    """Matching-engine restricted modes (Contract #2)."""

    NORMAL = "NORMAL"
    RESTARTING = "RESTARTING"  # HTTP 425 — back off + retry
    POST_ONLY = "POST_ONLY"  # switch flow, not retry
    CANCEL_ONLY = "CANCEL_ONLY"
    DISABLED = "DISABLED"
    UNKNOWN = "UNKNOWN"


class CancelStatus(Enum):
    ACKED = "ACKED"
    NOT_FOUND = "NOT_FOUND"
    NOT_CANCELED = "NOT_CANCELED"
    UNKNOWN = "UNKNOWN"


# Known error codes referenced by the post-only invariant + restricted modes.
ERR_POST_ONLY_CROSS_REJECT = "post_only_cross_reject"
ERR_ORDER_DELAYED = "ORDER_DELAYED"
ERR_FOK_NOT_FILLED = "FOK_ORDER_NOT_FILLED_ERROR"
ERR_MARKET_NOT_READY = "MARKET_NOT_READY"


# --- requests (split by intent) ---------------------------------------------
@dataclass(frozen=True, slots=True)
class PassivePostOnlyOrderRequest:
    """The ONLY request type v1 strategy emits. Must never cross.

    ``signed_payload`` / ``signed_payload_hash`` are the exact bytes resent
    verbatim on retry (do NOT re-salt — there is no native client_order_id, so
    the signed payload IS the idempotency anchor; PLAN §4.4).
    """

    local_intent_id: str
    condition_id: str
    asset_id: str
    side: Side
    price: Decimal
    size: Decimal
    order_type: OrderType  # GTC | GTD only
    tick_size: Decimal
    neg_risk: bool = False
    post_only: bool = True  # always; must never cross
    expiration: int | None = None  # epoch seconds; required iff GTD
    funder: str | None = None
    signature_type: int | None = None  # 0 EOA / 1 proxy / 2 safe / 3 POLY_1271
    signed_payload_hash: str | None = None
    signed_payload: str | None = None
    submit_attempt: int = 0


@dataclass(frozen=True, slots=True)
class AggressiveOrderRequest:
    """FOK/FAK/taker — NOT used by v1 strategy (M0 conformance probes only)."""

    local_intent_id: str
    condition_id: str
    asset_id: str
    side: Side
    price: Decimal
    size: Decimal
    order_type: OrderType  # FOK | FAK | GTC-taker
    tick_size: Decimal
    neg_risk: bool = False
    post_only: bool = False
    funder: str | None = None
    signature_type: int | None = None
    signed_payload_hash: str | None = None
    signed_payload: str | None = None
    submit_attempt: int = 0


# v1 strategy emits only the passive type; the port also carries aggressive
# requests for M0 conformance probes, so it accepts either typed shape.
type SubmitOrderRequest = PassivePostOnlyOrderRequest | AggressiveOrderRequest


@dataclass(frozen=True, slots=True)
class CancelOrderRequest:
    """Typed cancel request (no bare order-id string at the port boundary)."""

    order_id: str
    condition_id: str | None = None
    asset_id: str | None = None


# --- results ----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SubmitOrderResult:
    status: SubmitStatus
    http_status: int
    restricted_mode: RestrictedMode = RestrictedMode.NORMAL
    insert_status: InsertStatus | None = None
    exchange_order_id: str | None = None
    order_hash: str | None = None
    error_code: str | None = None
    retry_after_seconds: float | None = None  # MAY be absent (Cloudflare 429s)
    raw_response: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class OpenOrder:
    order_id: str
    asset_id: str
    side: Side
    price: Decimal
    size: Decimal
    size_matched: Decimal


@dataclass(frozen=True, slots=True)
class CancelOrderResult:
    """A REST cancel ACK is not the same as cancellation being effective — both
    timestamps are captured so §7 can measure cancel latency."""

    status: CancelStatus
    http_status: int
    request_monotonic_ts: float
    response_monotonic_ts: float
    restricted_mode: RestrictedMode = RestrictedMode.NORMAL
    canceled_ids: tuple[str, ...] = ()
    not_canceled: Mapping[str, str] = field(default_factory=dict)
    effective_confirmed_ts: float | None = None
    open_order_after_cancel: OpenOrder | None = None
    # fills_after_cancel — in-flight matches between request and response (§7).
    size_matched_delta_after_request: Decimal = Decimal("0")
    size_matched_delta_after_response: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class CancelResult:
    """Result of cancel_market_orders (cancel-all for a condition)."""

    status: CancelStatus
    http_status: int
    canceled_ids: tuple[str, ...] = ()
    restricted_mode: RestrictedMode = RestrictedMode.NORMAL


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    asset_id: str
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]
    hash: str | None = None


@dataclass(frozen=True, slots=True)
class HeartbeatRequest:
    """User-global deadman. ``previous_heartbeat_id`` is ``""`` on the first
    call, else the last ack's id (the chain; PLAN §6, Contract #2)."""

    previous_heartbeat_id: str = ""


@dataclass(frozen=True, slots=True)
class HeartbeatAck:
    heartbeat_id: str
    corrected_from_400: bool = False  # broken/expired chain → 400 returns correct id


@runtime_checkable
class ExchangePort(Protocol):
    """Typed CLOB port. Concrete impls live in WS-D (gated)."""

    def submit_order(self, request: SubmitOrderRequest) -> SubmitOrderResult: ...

    def cancel_order(self, request: CancelOrderRequest) -> CancelOrderResult: ...

    def cancel_market_orders(self, condition_id: str) -> CancelResult: ...

    def fetch_open_orders(self, condition_id: str | None = None) -> list[OpenOrder]: ...

    def fetch_book_snapshot(self, asset_id: str) -> BookSnapshot: ...

    def subscribe_market_events(
        self, condition_ids: list[str]
    ) -> Iterator[RecordedEvent]: ...

    def subscribe_user_events(self) -> Iterator[RecordedEvent]: ...

    def post_heartbeat(self, request: HeartbeatRequest) -> HeartbeatAck: ...


# --- post-only invariant (Contract #2) --------------------------------------
class PostOnlyOutcome(Enum):
    RESTED = "RESTED"  # insert_status=live — the only ACCEPTED outcome allowed
    REJECTED_CROSS = "REJECTED_CROSS"  # REJECTED(post_only_cross_reject) — allowed
    REJECTED_OTHER = "REJECTED_OTHER"  # rejected for an allowed reason (e.g. not-ready)
    UNKNOWN = "UNKNOWN"  # lost response — reconcile, do not breaker
    CONFORMANCE_FAILURE = "CONFORMANCE_FAILURE"  # matched/delayed/unmatched — breaker


class PostOnlyConformanceError(RuntimeError):
    """A post-only order resolved to matched/delayed/unmatched (or ACCEPTED but
    not provably live). This is a protocol breaker: halt and DO NOT treat it as
    a fill (PLAN §10 Contract #2)."""


def price_is_tick_aligned(price: Decimal, tick_size: Decimal) -> bool:
    """True iff ``price`` is an exact multiple of ``tick_size`` (Decimal-exact)."""
    if tick_size <= 0:
        return False
    return (price % tick_size) == 0


def post_only_request_violations(req: PassivePostOnlyOrderRequest) -> list[str]:
    """Return a list of invariant violations (empty list ⇒ the request is a
    submit-ready passive post-only order that cannot become a taker).

    A request may be built unsigned at INTENT and signed later, but a request
    handed to :meth:`ExchangePort.submit_order` MUST carry its signed payload:
    there is no native ``client_order_id``, so ``signed_payload`` (resent
    verbatim on retry) and ``signed_payload_hash`` ARE the idempotency anchor for
    UNKNOWN/lost-response reconciliation (PLAN §4.4, Contract #2). This gate is
    therefore run on the submit path, after signing."""
    issues: list[str] = []
    if req.order_type not in POST_ONLY_ORDER_TYPES:
        issues.append(
            f"order_type {req.order_type.value} not allowed for post-only (GTC/GTD only)"
        )
    if not req.post_only:
        issues.append("post_only must be True for a passive request")
    if not (Decimal("0") < req.price < Decimal("1")):
        issues.append(f"price {req.price} must be in the open interval (0, 1)")
    elif not price_is_tick_aligned(req.price, req.tick_size):
        issues.append(f"price {req.price} is not aligned to tick_size {req.tick_size}")
    if req.size <= 0:
        issues.append(f"size {req.size} must be positive")
    if req.order_type is OrderType.GTD and req.expiration is None:
        issues.append("GTD order requires an expiration")
    if req.order_type is OrderType.GTC and req.expiration is not None:
        issues.append("GTC order must not carry an expiration")
    if not req.signed_payload_hash:
        issues.append("signed_payload_hash is required (idempotency anchor; §4.4)")
    if not req.signed_payload:
        issues.append("signed_payload is required (resent verbatim on retry; §4.4)")
    return issues


def classify_post_only_result(result: SubmitOrderResult) -> PostOnlyOutcome:
    """Classify a submit result against the post-only invariant.

    An ACCEPTED post-only order MUST be ``insert_status='live'``; anything else
    accepted (matched/delayed/unmatched, or an absent insert_status we cannot
    confirm rested) is a conformance failure.
    """
    if result.status is SubmitStatus.UNKNOWN:
        return PostOnlyOutcome.UNKNOWN
    if result.status is SubmitStatus.REJECTED:
        if result.error_code == ERR_POST_ONLY_CROSS_REJECT:
            return PostOnlyOutcome.REJECTED_CROSS
        return PostOnlyOutcome.REJECTED_OTHER
    # status is ACCEPTED
    if result.insert_status is InsertStatus.LIVE:
        return PostOnlyOutcome.RESTED
    return PostOnlyOutcome.CONFORMANCE_FAILURE


def assert_post_only_conformance(result: SubmitOrderResult) -> PostOnlyOutcome:
    """Classify and raise :class:`PostOnlyConformanceError` on a breaker outcome.

    UNKNOWN does NOT raise — it is reconciled via REST + user WS (§4.4)."""
    outcome = classify_post_only_result(result)
    if outcome is PostOnlyOutcome.CONFORMANCE_FAILURE:
        insert = result.insert_status.value if result.insert_status else None
        raise PostOnlyConformanceError(
            f"post-only order resolved non-live: status={result.status.value}, "
            f"insert_status={insert}"
        )
    return outcome
