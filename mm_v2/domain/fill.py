"""Fill & settlement identity (WS-B, pure) — Contract #4.

A single logical trade can be split across multiple on-chain transactions (gas
limits), so we distinguish two keys (PLAN §3.2, §10 Contract #4):

* **logical-fill key** = ``(trade_id, maker_order_id)`` — derived from a trade
  event's ``maker_orders[]``. This is identity-stable across the WS frame and
  the later REST trade record for the same trade.
* **settlement-bucket key** = ``(trade_id, bucket_index, transaction_hash?)`` —
  only present once REST/on-chain metadata exists.

Settlement status (``CONFIRMED`` / ``FAILED`` / ``RETRYING``) MUST be tagged as
*logical-trade* scope vs *bucket* scope: a logical trade is only terminal once
**all** its buckets are terminal, so until then it is conservative unconfirmed
exposure (no early promote, no partial rollback at the wrong granularity).

This module is pure and imports nothing outside the domain. The bridge that
turns Contract #1b parsed trade events into these records lives in
``accounting/inventory_ledger.py`` (WS-C), which may depend on both feeds and
domain.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from mm_v2.domain.order import Outcome, Side


class SettlementStatus(Enum):
    """Trade settlement status set (PLAN §3.2, verified vs User Channel docs).

    ``MATCHED → MINED → CONFIRMED | FAILED`` with a non-terminal ``RETRYING``
    loop (tx reverted/reorged, operator resubmitting). Terminal = ``CONFIRMED``
    / ``FAILED`` only.
    """

    MATCHED = "MATCHED"
    MINED = "MINED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"

    @property
    def is_terminal(self) -> bool:
        """Only CONFIRMED / FAILED are terminal (PLAN §3.2)."""
        return self in (SettlementStatus.CONFIRMED, SettlementStatus.FAILED)

    @property
    def is_unconfirmed_exposure(self) -> bool:
        """True while the fill counts against ``unconfirmed_fill_cap``.

        Everything that is not yet ``CONFIRMED`` and not ``FAILED`` is held as
        unconfirmed exposure — including ``RETRYING`` (we neither roll back nor
        promote on a retry; we hold and run the age-based breaker).
        """
        return self in (
            SettlementStatus.MATCHED,
            SettlementStatus.MINED,
            SettlementStatus.RETRYING,
        )


class StatusScope(Enum):
    """Whether a settlement status applies to a logical trade or one bucket."""

    LOGICAL_TRADE = "LOGICAL_TRADE"
    BUCKET = "BUCKET"


# --- Identity keys (Contract #4) -------------------------------------------
LogicalFillKey = tuple[str, str]
SettlementBucketKey = tuple[str, int, str | None]
FillDedupKey = tuple[str, str, Decimal]


def logical_fill_key(trade_id: str, maker_order_id: str) -> LogicalFillKey:
    """Identity of a logical fill — stable across WS and REST records."""
    return (trade_id, maker_order_id)


def settlement_bucket_key(
    trade_id: str, bucket_index: int, transaction_hash: str | None
) -> SettlementBucketKey:
    """Identity of one settlement bucket (only meaningful with REST metadata)."""
    return (trade_id, bucket_index, transaction_hash)


def fill_dedup_key(
    trade_id: str, maker_order_id: str, cumulative_size_matched: Decimal
) -> FillDedupKey:
    """Idempotent dedup key for live/logical fills (PLAN §3.2)."""
    return (trade_id, maker_order_id, cumulative_size_matched)


@dataclass(frozen=True, slots=True)
class LogicalFill:
    """One maker-order match within a trade (the fill the ledger folds in).

    Derived from a trade event's ``maker_orders[]``. ``status`` is the
    logical-trade settlement status (WS frames start at ``MATCHED``); buckets
    are tracked separately in :class:`SettlementBucket`.
    """

    trade_id: str
    maker_order_id: str
    taker_order_id: str
    asset_id: str
    outcome: Outcome
    side: Side
    price: Decimal
    size: Decimal
    match_time: str
    status: SettlementStatus = SettlementStatus.MATCHED
    status_scope: StatusScope = StatusScope.LOGICAL_TRADE

    @property
    def key(self) -> LogicalFillKey:
        return logical_fill_key(self.trade_id, self.maker_order_id)


@dataclass(frozen=True, slots=True)
class SettlementBucket:
    """One on-chain settlement bucket for a trade (REST/on-chain metadata).

    A WS-only fill has no bucket yet and must NOT fabricate ``bucket_index`` /
    ``transaction_hash`` (Contract #1b / #4).
    """

    trade_id: str
    bucket_index: int
    match_time: str
    transaction_hash: str | None = None
    status: SettlementStatus = SettlementStatus.MINED
    status_scope: StatusScope = StatusScope.BUCKET

    @property
    def key(self) -> SettlementBucketKey:
        return settlement_bucket_key(
            self.trade_id, self.bucket_index, self.transaction_hash
        )


# --- logical-trade status aggregation (Contract #4 / §3.2) ------------------
# Settlement progress among the non-problem states (higher = more settled).
# FAILED / RETRYING are handled explicitly and are deliberately off this scale.
_SETTLEMENT_PROGRESS: dict[SettlementStatus, int] = {
    SettlementStatus.MATCHED: 0,
    SettlementStatus.MINED: 1,
    SettlementStatus.CONFIRMED: 2,
}


def aggregate_logical_status(
    statuses: Iterable[SettlementStatus],
) -> SettlementStatus:
    """Fold per-bucket statuses into the *logical-trade* status (PLAN §3.2).

    A logical trade is only terminal once **all** its buckets are terminal, so a
    single bucket's status must never be promoted — or rolled back — at the whole
    trade's granularity. Precedence:

    * empty bucket set ⇒ ``MATCHED`` (nothing proven settled yet);
    * **all** buckets terminal ⇒ ``FAILED`` if any bucket is ``FAILED``, else
      ``CONFIRMED`` (safe to promote to settlement / reconcile the failure);
    * otherwise (≥ 1 non-terminal bucket, so the trade is NOT terminal — hold as
      conservative unconfirmed exposure):

      * any ``FAILED`` or ``RETRYING`` bucket ⇒ ``RETRYING`` — surface the
        non-terminal problem state so the age-based reconcile/breaker runs;
        never a terminal status while buckets remain open (no early promote,
        no partial rollback at the wrong granularity);
      * else the least-settled non-terminal bucket (``MATCHED`` before
        ``MINED``; ``CONFIRMED`` buckets must not raise the floor).
    """
    seen = list(statuses)
    if not seen:
        return SettlementStatus.MATCHED
    if all(s.is_terminal for s in seen):
        # Every bucket is terminal ⇒ the logical trade is terminal too: a single
        # FAILED bucket fails the whole trade, otherwise all CONFIRMED.
        if any(s is SettlementStatus.FAILED for s in seen):
            return SettlementStatus.FAILED
        return SettlementStatus.CONFIRMED
    # ≥ 1 bucket is still non-terminal ⇒ the logical trade is NOT terminal.
    if any(
        s in (SettlementStatus.FAILED, SettlementStatus.RETRYING) for s in seen
    ):
        # A problem bucket is present but not all buckets are terminal: surface
        # non-terminal RETRYING (never terminal while buckets remain open).
        return SettlementStatus.RETRYING
    # Only MATCHED / MINED / CONFIRMED remain: report the least-settled
    # non-terminal bucket (CONFIRMED buckets must not raise the floor).
    return min(
        (s for s in seen if not s.is_terminal),
        key=lambda s: _SETTLEMENT_PROGRESS[s],
    )


def logical_status_from_buckets(
    buckets: Iterable[SettlementBucket],
) -> SettlementStatus:
    """Logical-trade status derived across a trade's settlement buckets (§3.2)."""
    return aggregate_logical_status(b.status for b in buckets)
