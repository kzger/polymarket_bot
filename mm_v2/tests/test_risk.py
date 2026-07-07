"""Risk model tests (WS-B) — PLAN §6.

The headline rule: the worst case is a *subset* of resting orders filling, not
all of them, so approving the next order must consider the **reachable**
directional interval, not just already-filled inventory:

    U₊ = Q(BUY_YES) + Q(SELL_NO)        # how far D could move up
    U₋ = Q(BUY_NO)  + Q(SELL_YES)       # how far D could move down
    reachable D ∈ [D₀ − U₋, D₀ + U₊]
    require: D₀ − U₋ ≥ −D_limit  and  D₀ + U₊ ≤ D_limit
"""

from __future__ import annotations

from decimal import Decimal

from mm_v2.domain.inventory import InventoryState
from mm_v2.domain.routing import ExposureRoute
from mm_v2.domain.risk import (
    RiskLimits,
    assess_new_order,
    caps_violations,
    directional_interval_within_limit,
    reachable_directional_interval,
)


def test_reachable_interval_is_asymmetric_subset_fill() -> None:
    pending = {
        ExposureRoute.BUY_YES: Decimal("10"),
        ExposureRoute.SELL_NO: Decimal("2"),  # U+ = 12
        ExposureRoute.BUY_NO: Decimal("4"),
        ExposureRoute.SELL_YES: Decimal("1"),  # U- = 5
    }
    lo, hi = reachable_directional_interval(Decimal("5"), pending)
    assert lo == Decimal("0")  # 5 - 5
    assert hi == Decimal("17")  # 5 + 12


def test_empty_pending_interval_is_just_d0() -> None:
    lo, hi = reachable_directional_interval(Decimal("3"), {})
    assert lo == Decimal("3")
    assert hi == Decimal("3")


def test_within_limit_when_both_tails_inside() -> None:
    pending = {ExposureRoute.BUY_YES: Decimal("10"), ExposureRoute.BUY_NO: Decimal("4")}
    assert directional_interval_within_limit(Decimal("5"), pending, Decimal("20")) is True


def test_upper_tail_breach_rejected() -> None:
    pending = {ExposureRoute.BUY_YES: Decimal("12")}  # hi = 5 + 12 = 17
    assert directional_interval_within_limit(Decimal("5"), pending, Decimal("15")) is False


def test_lower_tail_breach_rejected() -> None:
    pending = {ExposureRoute.BUY_NO: Decimal("10")}  # lo = -12 - 10 = -22
    assert directional_interval_within_limit(Decimal("-12"), pending, Decimal("20")) is False


def test_assess_new_order_rejects_when_candidate_pushes_over_upper_limit() -> None:
    limits = RiskLimits(directional_unmatched_limit=Decimal("15"))
    pending = {ExposureRoute.BUY_YES: Decimal("10")}  # hi already at 15 with d0=5
    inv = InventoryState()
    # adding 1 more BUY_YES would make reachable hi = 16 > 15
    decision = assess_new_order(
        inv, limits, pending, ExposureRoute.BUY_YES, Decimal("1"), d0=Decimal("5")
    )
    assert decision.approved is False
    assert any("directional" in v.lower() for v in decision.violations)
    assert decision.reachable_interval == (Decimal("5"), Decimal("16"))


def test_assess_new_order_approves_opposing_leg_that_does_not_widen_upper_tail() -> None:
    limits = RiskLimits(directional_unmatched_limit=Decimal("15"))
    pending = {ExposureRoute.BUY_YES: Decimal("10")}
    inv = InventoryState()
    # a SELL_YES leg moves the lower tail, not the upper one near the limit
    decision = assess_new_order(
        inv, limits, pending, ExposureRoute.SELL_YES, Decimal("1"), d0=Decimal("5")
    )
    assert decision.approved is True
    assert decision.violations == ()


def test_caps_violations_flags_each_breached_cap() -> None:
    limits = RiskLimits(
        directional_unmatched_limit=Decimal("100"),
        paired_inventory_cap=Decimal("5"),
        collateral_reserved_cap=Decimal("10"),
        pending_ctf_operation_cap=Decimal("3"),
        unconfirmed_fill_cap=Decimal("2"),
    )
    inv = InventoryState(
        yes_free=Decimal("7"),
        no_free=Decimal("7"),  # P = min(7,7) = 7 > paired cap 5
        collateral_reserved_for_bids=Decimal("20"),  # > 10
        pending_splits=Decimal("2"),
        pending_merges=Decimal("2"),  # 4 > 3
        matched_unconfirmed_fill_gross=Decimal("3"),  # 3 > 2
    )
    violations = caps_violations(inv, limits)
    joined = " ".join(violations).lower()
    assert "paired" in joined
    assert "collateral" in joined
    assert "pending_ctf" in joined or "ctf" in joined
    assert "unconfirmed" in joined


def test_caps_violations_empty_when_within_limits() -> None:
    limits = RiskLimits(
        directional_unmatched_limit=Decimal("100"),
        paired_inventory_cap=Decimal("100"),
        collateral_reserved_cap=Decimal("100"),
        pending_ctf_operation_cap=Decimal("100"),
        unconfirmed_fill_cap=Decimal("100"),
    )
    assert caps_violations(InventoryState(), limits) == []


def test_assess_new_order_rejects_candidate_reservation_over_collateral_cap() -> None:
    # Pre-order reservation is UNDER the cap, but THIS bid's own collateral
    # reservation pushes it over. It must be rejected even though the directional
    # tail is fine — the candidate must be projected into collateral_reserved_cap
    # (§6), not just the directional interval.
    limits = RiskLimits(
        directional_unmatched_limit=Decimal("100"),
        collateral_reserved_cap=Decimal("50"),
    )
    inv = InventoryState(collateral_reserved_for_bids=Decimal("40"))  # under 50
    decision = assess_new_order(
        inv,
        limits,
        {},
        ExposureRoute.BUY_YES,
        Decimal("20"),
        d0=Decimal("0"),
        candidate_collateral_reservation=Decimal("15"),  # 40 + 15 = 55 > 50
    )
    assert decision.approved is False
    assert any("collateral" in v.lower() for v in decision.violations)


def test_assess_new_order_approves_when_candidate_reservation_within_cap() -> None:
    limits = RiskLimits(
        directional_unmatched_limit=Decimal("100"),
        collateral_reserved_cap=Decimal("50"),
    )
    inv = InventoryState(collateral_reserved_for_bids=Decimal("40"))
    decision = assess_new_order(
        inv,
        limits,
        {},
        ExposureRoute.BUY_YES,
        Decimal("5"),
        d0=Decimal("0"),
        candidate_collateral_reservation=Decimal("5"),  # 40 + 5 = 45 <= 50
    )
    assert decision.approved is True
    assert decision.violations == ()


def test_assess_new_order_reservation_defaults_to_zero_backward_compatible() -> None:
    # Without a supplied reservation the caps are checked on current inventory,
    # so an existing over-cap reservation is flagged but a new order adds nothing.
    limits = RiskLimits(
        directional_unmatched_limit=Decimal("100"),
        collateral_reserved_cap=Decimal("50"),
    )
    inv = InventoryState(collateral_reserved_for_bids=Decimal("30"))
    decision = assess_new_order(
        inv, limits, {}, ExposureRoute.BUY_YES, Decimal("5"), d0=Decimal("0")
    )
    assert decision.approved is True


def test_assess_new_order_rejects_candidate_buy_that_would_breach_paired_cap() -> None:
    # Holding 10 NO; a BUY_YES of 6 would create P = min(6, 10) = 6 on fill, over
    # the paired cap of 5 — must be rejected even though the directional tail is
    # fine. The candidate's fill-side token delta must be projected into the
    # paired_inventory_cap check, not just the pre-order tokens (§6).
    limits = RiskLimits(
        directional_unmatched_limit=Decimal("100"),
        paired_inventory_cap=Decimal("5"),
    )
    inv = InventoryState(no_free=Decimal("10"))
    decision = assess_new_order(
        inv, limits, {}, ExposureRoute.BUY_YES, Decimal("6"), d0=Decimal("-10")
    )
    assert decision.approved is False
    assert any("paired" in v.lower() for v in decision.violations)


def test_assess_new_order_approves_buy_within_paired_cap() -> None:
    limits = RiskLimits(
        directional_unmatched_limit=Decimal("100"),
        paired_inventory_cap=Decimal("5"),
    )
    inv = InventoryState(no_free=Decimal("10"))
    # P = min(4, 10) = 4 <= 5
    decision = assess_new_order(
        inv, limits, {}, ExposureRoute.BUY_YES, Decimal("4"), d0=Decimal("-10")
    )
    assert decision.approved is True


def test_assess_new_order_sell_is_not_projected_as_paired_increase() -> None:
    # A SELL can only reduce paired on fill, so the worst case for the paired cap
    # is the sell NOT filling; it must not be projected as a paired increase.
    limits = RiskLimits(
        directional_unmatched_limit=Decimal("100"),
        paired_inventory_cap=Decimal("5"),
    )
    inv = InventoryState(yes_free=Decimal("4"), no_free=Decimal("4"))  # P = 4 <= 5
    decision = assess_new_order(
        inv, limits, {}, ExposureRoute.SELL_YES, Decimal("6"), d0=Decimal("0")
    )
    assert decision.approved is True


def test_caps_unconfirmed_uses_gross_not_net_of_offsetting_fills() -> None:
    # BUY_YES 10 and SELL_YES 10, both still unsettled, net to 0 in the signed
    # field but are 20 of GROSS outstanding unsettled fills → the cap must trip.
    limits = RiskLimits(
        directional_unmatched_limit=Decimal("100"),
        unconfirmed_fill_cap=Decimal("5"),
    )
    inv = InventoryState(
        matched_unconfirmed_yes=Decimal("0"),  # +10 buy, -10 sell → net 0
        matched_unconfirmed_fill_gross=Decimal("20"),
    )
    assert any("unconfirmed" in v.lower() for v in caps_violations(inv, limits))


def test_assess_new_order_rejects_buy_that_pushes_gross_over_unconfirmed_cap() -> None:
    limits = RiskLimits(
        directional_unmatched_limit=Decimal("100"),
        paired_inventory_cap=Decimal("100"),
        unconfirmed_fill_cap=Decimal("5"),
    )
    inv = InventoryState(matched_unconfirmed_fill_gross=Decimal("4"))
    decision = assess_new_order(
        inv, limits, {}, ExposureRoute.BUY_YES, Decimal("3"), d0=Decimal("0")
    )  # gross 4 + 3 = 7 > 5
    assert decision.approved is False
    assert any("unconfirmed" in v.lower() for v in decision.violations)


def test_assess_new_order_rejects_sell_that_pushes_gross_over_unconfirmed_cap() -> None:
    # A SELL fill is also outstanding unsettled exposure, so it must project into
    # the gross unconfirmed cap even though it does not raise paired inventory.
    limits = RiskLimits(
        directional_unmatched_limit=Decimal("100"),
        paired_inventory_cap=Decimal("100"),
        unconfirmed_fill_cap=Decimal("5"),
    )
    inv = InventoryState(
        yes_free=Decimal("10"),  # tokens to sell
        matched_unconfirmed_fill_gross=Decimal("4"),
    )
    decision = assess_new_order(
        inv, limits, {}, ExposureRoute.SELL_YES, Decimal("3"), d0=Decimal("0")
    )  # gross 4 + 3 = 7 > 5
    assert decision.approved is False
    assert any("unconfirmed" in v.lower() for v in decision.violations)


# --- reachable-fill projection (resting orders + candidate) ------------------
_WIDE = dict(
    directional_unmatched_limit=Decimal("1000"),
    paired_inventory_cap=Decimal("1000"),
)


def test_gross_cap_includes_reachable_resting_orders() -> None:
    # unconfirmed_fill_cap=10; a resting 9-share order + a new 9-share candidate
    # can both match before settlement → 18 gross → rejected (was approved when
    # only the candidate was projected).
    limits = RiskLimits(unconfirmed_fill_cap=Decimal("10"), **_WIDE)
    pending = {ExposureRoute.BUY_YES: Decimal("9")}
    decision = assess_new_order(
        InventoryState(), limits, pending, ExposureRoute.BUY_YES, Decimal("9"),
        d0=Decimal("0"),
    )  # projected gross = 9 + 9 = 18 > 10
    assert decision.approved is False
    assert any("unconfirmed" in v.lower() for v in decision.violations)


def test_gross_cap_approves_when_reachable_within_cap() -> None:
    limits = RiskLimits(unconfirmed_fill_cap=Decimal("10"), **_WIDE)
    pending = {ExposureRoute.BUY_YES: Decimal("3")}
    decision = assess_new_order(
        InventoryState(), limits, pending, ExposureRoute.BUY_YES, Decimal("3"),
        d0=Decimal("0"),
    )  # gross 3 + 3 = 6 <= 10
    assert decision.approved is True


def test_gross_cap_never_nets_across_offsetting_routes() -> None:
    # A resting BUY_YES 6 and a candidate SELL_YES 6 net to zero directionally,
    # but gross settlement exposure does not net → projected 12 > 10 → rejected.
    limits = RiskLimits(unconfirmed_fill_cap=Decimal("10"), **_WIDE)
    pending = {ExposureRoute.BUY_YES: Decimal("6")}
    inv = InventoryState(yes_free=Decimal("6"))  # tokens to sell
    decision = assess_new_order(
        inv, limits, pending, ExposureRoute.SELL_YES, Decimal("6"), d0=Decimal("0")
    )  # gross = 6 (resting buy) + 6 (candidate sell) = 12 > 10
    assert decision.approved is False
    assert any("unconfirmed" in v.lower() for v in decision.violations)


def test_gross_cap_trips_when_pending_alone_near_cap() -> None:
    # Existing reachable pending is already at the cap; a small candidate on a
    # different route pushes it over.
    limits = RiskLimits(unconfirmed_fill_cap=Decimal("10"), **_WIDE)
    pending = {ExposureRoute.BUY_YES: Decimal("10")}
    decision = assess_new_order(
        InventoryState(), limits, pending, ExposureRoute.BUY_NO, Decimal("1"),
        d0=Decimal("0"),
    )  # gross = 10 + 1 = 11 > 10
    assert decision.approved is False


def test_paired_cap_includes_reachable_resting_buys() -> None:
    # 10 NO, cap 5; a resting BUY_YES 4 + a new BUY_YES 2 can both fill → P =
    # min(6, 10) = 6 > 5 → rejected, though a candidate-only projection (2) would
    # approve.
    limits = RiskLimits(
        directional_unmatched_limit=Decimal("1000"),
        paired_inventory_cap=Decimal("5"),
    )
    inv = InventoryState(no_free=Decimal("10"))
    pending = {ExposureRoute.BUY_YES: Decimal("4")}
    decision = assess_new_order(
        inv, limits, pending, ExposureRoute.BUY_YES, Decimal("2"), d0=Decimal("-10")
    )
    assert decision.approved is False
    assert any("paired" in v.lower() for v in decision.violations)
