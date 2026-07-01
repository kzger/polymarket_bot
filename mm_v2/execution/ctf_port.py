"""Contract #2 — ``CtfPort`` interface + ``CtfOpResult``.

Complete-set split / merge / redeem are core inventory primitives from M1
(PLAN §3.4), abstracted behind this port so the CTF execution path (direct
on-chain vs gasless relayer — UNDECIDED, PLAN §11) never leaks into domain.

The relayer returns ``{transactionID, state:"STATE_NEW"}`` and the on-chain hash
arrives later via polling, so an op is ``PENDING`` until proven terminal; a
timeout surfaces as ``UNKNOWN`` (never an exception only), mirroring the order
lifecycle.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class Terminality(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"

    @property
    def is_terminal(self) -> bool:
        return self in (Terminality.CONFIRMED, Terminality.FAILED)


@dataclass(frozen=True, slots=True)
class CtfOpResult:
    local_op_id: str
    terminality: Terminality
    transaction_id: str | None = None  # relayer STATE_NEW id, poll GET /transaction
    tx_hash: str | None = None
    status_raw: str | None = None
    error: str | None = None
    raw_response: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class Balances:
    """Snapshot of on-chain/CTF balances for a condition (terminal truth)."""

    condition_id: str
    collateral: Decimal
    yes: Decimal
    no: Decimal


@runtime_checkable
class CtfPort(Protocol):
    """Typed CTF port. Concrete impls live in WS-D (gated)."""

    def split(self, condition_id: str, amount: Decimal) -> CtfOpResult: ...

    def merge(self, condition_id: str, amount: Decimal) -> CtfOpResult: ...

    def redeem(self, condition_id: str, amount: Decimal) -> CtfOpResult: ...

    def fetch_balances(self, condition_id: str) -> Balances: ...
