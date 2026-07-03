"""InventoryState + balance basis (WS-B, pure) — PLAN §4.2, Contract #3.

Inventory is *derived* from an immutable fill ledger + CTF ops, never a mutated
running total (core invariant #2). This module holds the derived state and the
two frozen balance bases (Contract #3):

* ``shadow_owned_total`` — confirmed balances + tokens reserved for resting
  asks/bids + MATCHED-but-unconfirmed fills, **excluding** non-terminal CTF
  pending (splits/merges that could still fail). This is the ONLY basis for
  ``D`` / ``P`` / ``W_min`` (risk, quoter, allocator all read it — no ad hoc
  recomputation from raw fields).
* ``available_to_order`` — free, unreserved, terminal-only balances. This is the
  ONLY basis for new-order capacity. Never use ``shadow_owned_total`` for
  capacity, and never use ``available_to_order`` for ``D``/``P``/``W_min``.

Worst-case terminal value uses ``W_min = C + min(Y, N)`` — never USDC notional.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class InventoryState:
    """Derived per-condition inventory (PLAN §4.2).

    Fields are grouped by basis so the two Contract #3 accessors can be computed
    without ambiguity:

    * terminal confirmed balances, split into free vs reserved-for-resting-orders
    * MATCHED-but-unconfirmed fill deltas (signed: tokens gained are positive,
      collateral spent is negative)
    * gross outstanding unsettled-fill quantity (``matched_unconfirmed_fill_gross``,
      unsigned) — the ``unconfirmed_fill_cap`` basis only; NOT a balance basis
    * non-terminal CTF pending (excluded from ``shadow_owned_total``)

    The signed ``matched_unconfirmed_*`` fields are the NET basis for
    ``shadow_owned``/``directional``; ``matched_unconfirmed_fill_gross`` is the
    GROSS basis for the settlement-risk cap (offsetting unsettled fills must not
    net to zero). The two frozen Contract #3 accessors below are unchanged.
    """

    # terminal confirmed (free vs committed to resting orders)
    collateral_free: Decimal = _ZERO
    collateral_reserved_for_bids: Decimal = _ZERO
    yes_free: Decimal = _ZERO
    yes_reserved_for_asks: Decimal = _ZERO
    no_free: Decimal = _ZERO
    no_reserved_for_asks: Decimal = _ZERO
    # MATCHED but not yet CONFIRMED (shadow only; signed deltas)
    matched_unconfirmed_collateral: Decimal = _ZERO
    matched_unconfirmed_yes: Decimal = _ZERO
    matched_unconfirmed_no: Decimal = _ZERO
    # GROSS outstanding unsettled-fill quantity (sum of |size| over non-terminal
    # fills; never nets). Basis for unconfirmed_fill_cap ONLY — deliberately NOT
    # part of shadow_owned_* / available_* (Contract #3). Populated by the ledger
    # fold via domain.fill.gross_unconfirmed_fill_quantity; defaults to 0.
    matched_unconfirmed_fill_gross: Decimal = _ZERO
    # non-terminal CTF pending (EXCLUDED from shadow_owned_total — Contract #3)
    pending_splits: Decimal = _ZERO  # complete-set qty: collateral → YES + NO
    pending_merges: Decimal = _ZERO  # complete-set qty: YES + NO → collateral

    # --- shadow_owned_total basis (risk / quoter / allocator — Contract #3) ---
    @property
    def shadow_owned_yes(self) -> Decimal:
        return self.yes_free + self.yes_reserved_for_asks + self.matched_unconfirmed_yes

    @property
    def shadow_owned_no(self) -> Decimal:
        return self.no_free + self.no_reserved_for_asks + self.matched_unconfirmed_no

    @property
    def shadow_owned_collateral(self) -> Decimal:
        return (
            self.collateral_free
            + self.collateral_reserved_for_bids
            + self.matched_unconfirmed_collateral
        )

    # --- available_to_order basis (new-order capacity ONLY — Contract #3) -----
    @property
    def available_yes(self) -> Decimal:
        return self.yes_free

    @property
    def available_no(self) -> Decimal:
        return self.no_free

    @property
    def available_collateral(self) -> Decimal:
        return self.collateral_free

    # --- derived quantities (all on the shadow_owned_total basis) -------------
    @property
    def directional_inventory(self) -> Decimal:
        """D = Y − N (D > 0 net YES, D < 0 net NO)."""
        return self.shadow_owned_yes - self.shadow_owned_no

    @property
    def mergeable_set_quantity(self) -> Decimal:
        """P = min(Y, N) — complete sets that can be merged."""
        return min(self.shadow_owned_yes, self.shadow_owned_no)

    @property
    def worst_case_terminal_value(self) -> Decimal:
        """W_min = C + min(Y, N) — worst-case terminal value (NOT USDC notional)."""
        return self.shadow_owned_collateral + self.mergeable_set_quantity

    @property
    def value_if_yes_resolves(self) -> Decimal:
        """W_YES = C + Y."""
        return self.shadow_owned_collateral + self.shadow_owned_yes

    @property
    def value_if_no_resolves(self) -> Decimal:
        """W_NO = C + N."""
        return self.shadow_owned_collateral + self.shadow_owned_no
