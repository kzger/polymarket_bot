"""Risk model (WS-B, pure) — PLAN §6.

Two independent limits plus supporting caps. The directional limit is enforced
against the **reachable** interval (a subset of resting orders filling), not just
already-filled inventory — approving the next order must consider where ``D``
*could* go, on both tails:

    U₊ = Q(BUY_YES) + Q(SELL_NO)
    U₋ = Q(BUY_NO)  + Q(SELL_YES)
    reachable D ∈ [D₀ − U₋, D₀ + U₊]
    require: D₀ − U₋ ≥ −D_limit  and  D₀ + U₊ ≤ D_limit

All quantities are on the Contract #3 ``shadow_owned_total`` basis (via
:class:`~mm_v2.domain.inventory.InventoryState`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal

from mm_v2.domain.inventory import InventoryState
from mm_v2.domain.routing import ROUTE_DIRECTIONAL_SIGN, ExposureRoute

_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """Directional tail-risk limit + supporting caps (PLAN §6)."""

    directional_unmatched_limit: Decimal  # primary tail risk: single-leg fills
    paired_inventory_cap: Decimal = Decimal("Infinity")
    collateral_reserved_cap: Decimal = Decimal("Infinity")
    pending_ctf_operation_cap: Decimal = Decimal("Infinity")
    unconfirmed_fill_cap: Decimal = Decimal("Infinity")


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    approved: bool
    violations: tuple[str, ...]
    reachable_interval: tuple[Decimal, Decimal]


def reachable_directional_interval(
    d0: Decimal, pending_by_route: Mapping[ExposureRoute, Decimal]
) -> tuple[Decimal, Decimal]:
    """Return ``(D₀ − U₋, D₀ + U₊)`` — the interval D could reach if any subset
    of the currently-resting orders fills."""
    u_plus = sum(
        (size for route, size in pending_by_route.items() if ROUTE_DIRECTIONAL_SIGN[route] > 0),
        _ZERO,
    )
    u_minus = sum(
        (size for route, size in pending_by_route.items() if ROUTE_DIRECTIONAL_SIGN[route] < 0),
        _ZERO,
    )
    return (d0 - u_minus, d0 + u_plus)


def directional_interval_within_limit(
    d0: Decimal,
    pending_by_route: Mapping[ExposureRoute, Decimal],
    d_limit: Decimal,
) -> bool:
    """True iff both reachable tails are within ``±d_limit``."""
    lo, hi = reachable_directional_interval(d0, pending_by_route)
    return lo >= -d_limit and hi <= d_limit


def caps_violations(inventory: InventoryState, limits: RiskLimits) -> list[str]:
    """Check the supporting caps (paired set, reserved collateral, pending CTF,
    unconfirmed fills). Returns a list of human-readable violations (empty ⇒ ok).
    """
    issues: list[str] = []

    paired = inventory.mergeable_set_quantity
    if paired > limits.paired_inventory_cap:
        issues.append(
            f"paired_inventory_cap: P={paired} > {limits.paired_inventory_cap}"
        )

    reserved = inventory.collateral_reserved_for_bids
    if reserved > limits.collateral_reserved_cap:
        issues.append(
            f"collateral_reserved_cap: {reserved} > {limits.collateral_reserved_cap}"
        )

    pending_ctf = inventory.pending_splits + inventory.pending_merges
    if pending_ctf > limits.pending_ctf_operation_cap:
        issues.append(
            f"pending_ctf_operation_cap: {pending_ctf} > {limits.pending_ctf_operation_cap}"
        )

    unconfirmed = inventory.matched_unconfirmed_fill_gross
    if unconfirmed > limits.unconfirmed_fill_cap:
        issues.append(
            f"unconfirmed_fill_cap: {unconfirmed} > {limits.unconfirmed_fill_cap}"
        )

    return issues


def assess_new_order(
    inventory: InventoryState,
    limits: RiskLimits,
    pending_by_route: Mapping[ExposureRoute, Decimal],
    candidate_route: ExposureRoute,
    candidate_size: Decimal,
    *,
    d0: Decimal | None = None,
    candidate_collateral_reservation: Decimal = _ZERO,
) -> RiskAssessment:
    """Assess whether placing ``candidate_size`` of ``candidate_route`` keeps the
    reachable directional interval within the limit AND respects the caps.

    ``d0`` defaults to the inventory's current directional inventory; it is a
    parameter so callers can probe hypothetical states.

    Fill-based caps are checked on the **reachable** set — the resting orders in
    ``pending_by_route`` plus this candidate — because gross and paired inventory
    accrue at FILL, not placement (§6, the same basis as the directional interval):

    * ``unconfirmed_fill_cap`` (GROSS, never nets): projected as
      ``matched_unconfirmed_fill_gross + Σ reachable fills`` over **all** routes —
      any fill (BUY or SELL) is outstanding unsettled exposure.
    * ``paired_inventory_cap`` (``P = min(Y, N)``): reachable **BUY** fills acquire
      tokens on their outcome side; SELLs only reduce paired, so are not projected
      (worst case is they do not fill).

    ``collateral_reserved_cap`` is the exception: collateral is reserved at
    PLACEMENT, so resting bids already sit in ``collateral_reserved_for_bids`` and
    only this order's marginal ``candidate_collateral_reservation`` (``size*price``
    for a bid, ``0`` for an ask) is added. Each projection touches an independent
    cap field, so every cap sees its own worst case.
    """
    if d0 is None:
        d0 = inventory.directional_inventory

    projected: dict[ExposureRoute, Decimal] = dict(pending_by_route)
    projected[candidate_route] = projected.get(candidate_route, _ZERO) + candidate_size

    lo, hi = reachable_directional_interval(d0, projected)
    d_limit = limits.directional_unmatched_limit

    # gross never nets: every reachable fill (all routes) is unsettled exposure.
    proj_kwargs: dict[str, Decimal] = {
        "matched_unconfirmed_fill_gross": (
            inventory.matched_unconfirmed_fill_gross + sum(projected.values(), _ZERO)
        ),
    }
    if candidate_collateral_reservation:
        proj_kwargs["collateral_reserved_for_bids"] = (
            inventory.collateral_reserved_for_bids + candidate_collateral_reservation
        )
    # paired P = min(Y, N): reachable BUY fills acquire tokens on their side.
    reachable_buy_yes = sum(
        (q for r, q in projected.items() if r is ExposureRoute.BUY_YES), _ZERO
    )
    reachable_buy_no = sum(
        (q for r, q in projected.items() if r is ExposureRoute.BUY_NO), _ZERO
    )
    if reachable_buy_yes:
        proj_kwargs["matched_unconfirmed_yes"] = (
            inventory.matched_unconfirmed_yes + reachable_buy_yes
        )
    if reachable_buy_no:
        proj_kwargs["matched_unconfirmed_no"] = (
            inventory.matched_unconfirmed_no + reachable_buy_no
        )
    projected_inventory = replace(inventory, **proj_kwargs)

    violations: list[str] = []
    if not (lo >= -d_limit and hi <= d_limit):
        violations.append(
            f"directional reachable interval [{lo}, {hi}] breaches ±{d_limit}"
        )
    violations.extend(caps_violations(projected_inventory, limits))

    return RiskAssessment(
        approved=not violations,
        violations=tuple(violations),
        reachable_interval=(lo, hi),
    )
