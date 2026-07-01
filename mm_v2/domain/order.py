"""Order value objects and lifecycle enums (WS-B, pure).

PLAN §4.4: the order lifecycle is an explicit state machine including
``UNKNOWN`` (a lost response / timeout is never assumed to be a failure). The
``Order`` record here is a pure value object; the transition logic lives in
``execution/order_state_machine.py`` (WS-D).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class Side(Enum):
    """Taker/intent side of an order or trade."""

    BUY = "BUY"
    SELL = "SELL"


class TradeSideConvention(Enum):
    """How to read the ``side`` field on a WS trade frame (PLAN §8 — UNPROVEN).

    Polymarket's exact trade-side semantics are not yet verified on our wallet;
    §8 requires this stay configurable until an M0 controlled buy/sell probe
    freezes it as a regression test. ``TAKER_SIDE`` (the current default
    assumption) means ``trade.side`` is the *taker's* side, so a maker fill is
    the opposite side; ``MAKER_SIDE`` means ``trade.side`` already denotes the
    maker's own side. REST maker fills are unaffected — they carry an explicit
    per-maker ``side``.
    """

    TAKER_SIDE = "TAKER_SIDE"
    MAKER_SIDE = "MAKER_SIDE"


class Outcome(Enum):
    """Which token of a binary market a quantity refers to."""

    YES = "YES"
    NO = "NO"


class OrderType(Enum):
    """Time-in-force. post-only forbids FOK/FAK (PLAN §3.5, Contract #2)."""

    GTC = "GTC"
    GTD = "GTD"
    FOK = "FOK"  # aggressive only (M0 probes); never emitted by v1 strategy
    FAK = "FAK"  # aggressive only (M0 probes); never emitted by v1 strategy


# Post-only quoting is GTC/GTD only.
POST_ONLY_ORDER_TYPES: frozenset[OrderType] = frozenset({OrderType.GTC, OrderType.GTD})


class OrderState(Enum):
    """Explicit lifecycle states (PLAN §4.4).

    ``UNKNOWN`` is a first-class state reached on a lost response / timeout; a
    reconciler resolves it via REST + user WS. Never collapse ``UNKNOWN`` into
    ``REJECTED``.
    """

    INTENT = "INTENT"
    PENDING_NEW = "PENDING_NEW"
    LIVE = "LIVE"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    PENDING_CANCEL = "PENDING_CANCEL"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


# Terminal states no reconciler will move out of.
TERMINAL_ORDER_STATES: frozenset[OrderState] = frozenset(
    {OrderState.FILLED, OrderState.CANCELED, OrderState.REJECTED}
)


@dataclass(frozen=True, slots=True)
class Order:
    """A single resting/working order, keyed by our ``local_intent_id``.

    There is no native ``client_order_id`` (PLAN §4.4), so idempotency is keyed
    on ``local_intent_id`` plus the exact ``signed_payload_hash`` that is resent
    verbatim on retry. ``exchange_order_id`` is populated once the venue
    acknowledges the order.
    """

    local_intent_id: str
    condition_id: str
    asset_id: str
    outcome: Outcome
    side: Side
    price: Decimal
    size: Decimal
    order_type: OrderType
    state: OrderState = OrderState.INTENT
    size_matched: Decimal = Decimal("0")
    post_only: bool = True
    expiration: int | None = None  # epoch seconds; required for GTD
    exchange_order_id: str | None = None
    signed_payload_hash: str | None = None
    submit_attempt: int = 0

    @property
    def remaining_size(self) -> Decimal:
        """Unfilled quantity still working in the book."""
        return self.size - self.size_matched
