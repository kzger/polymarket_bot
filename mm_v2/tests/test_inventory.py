"""Contract #3 balance-basis + inventory math tests (WS-B).

Verifies the two frozen bases never bleed into each other:
* ``shadow_owned_total`` = confirmed + reserved + MATCHED-unconfirmed, EXCLUDING
  non-terminal CTF pending — and is the basis for D / P / W_min.
* ``available_to_order`` = free, unreserved, terminal-only — the basis for new
  order capacity.
"""

from __future__ import annotations

from decimal import Decimal

from mm_v2.domain.inventory import InventoryState


def test_empty_inventory_is_all_zero() -> None:
    inv = InventoryState()
    assert inv.shadow_owned_yes == Decimal("0")
    assert inv.shadow_owned_no == Decimal("0")
    assert inv.shadow_owned_collateral == Decimal("0")
    assert inv.directional_inventory == Decimal("0")
    assert inv.mergeable_set_quantity == Decimal("0")
    assert inv.worst_case_terminal_value == Decimal("0")


def build_inventory() -> InventoryState:
    return InventoryState(
        collateral_free=Decimal("100"),
        collateral_reserved_for_bids=Decimal("20"),
        yes_free=Decimal("10"),
        yes_reserved_for_asks=Decimal("4"),
        no_free=Decimal("6"),
        no_reserved_for_asks=Decimal("1"),
        matched_unconfirmed_yes=Decimal("3"),
        matched_unconfirmed_collateral=Decimal("-1.56"),  # bought 3 YES @ 0.52
        pending_splits=Decimal("5"),
        pending_merges=Decimal("2"),
    )


def test_shadow_owned_includes_confirmed_reserved_and_unconfirmed() -> None:
    inv = build_inventory()
    # 14 confirmed YES (10 free + 4 reserved) + 3 matched-unconfirmed
    assert inv.shadow_owned_yes == Decimal("17")
    # 7 confirmed NO (6 + 1) + 0 unconfirmed
    assert inv.shadow_owned_no == Decimal("7")
    # 120 confirmed collateral (100 + 20) + (-1.56) spent on the unconfirmed buy
    assert inv.shadow_owned_collateral == Decimal("118.44")


def test_shadow_owned_excludes_non_terminal_ctf_pending() -> None:
    inv = build_inventory()
    huge_pending = InventoryState(
        collateral_free=inv.collateral_free,
        collateral_reserved_for_bids=inv.collateral_reserved_for_bids,
        yes_free=inv.yes_free,
        yes_reserved_for_asks=inv.yes_reserved_for_asks,
        no_free=inv.no_free,
        no_reserved_for_asks=inv.no_reserved_for_asks,
        matched_unconfirmed_yes=inv.matched_unconfirmed_yes,
        matched_unconfirmed_collateral=inv.matched_unconfirmed_collateral,
        pending_splits=Decimal("9999"),  # must not be credited
        pending_merges=Decimal("9999"),
    )
    # Pending splits/merges could still fail, so they never move the shadow basis.
    assert huge_pending.shadow_owned_yes == inv.shadow_owned_yes
    assert huge_pending.shadow_owned_no == inv.shadow_owned_no
    assert huge_pending.shadow_owned_collateral == inv.shadow_owned_collateral
    assert huge_pending.directional_inventory == inv.directional_inventory


def test_available_to_order_is_free_terminal_only() -> None:
    inv = build_inventory()
    # available uses ONLY *_free — never reserved, unconfirmed, or pending CTF
    assert inv.available_yes == Decimal("10")
    assert inv.available_no == Decimal("6")
    assert inv.available_collateral == Decimal("100")
    # the two bases are genuinely different
    assert inv.available_yes != inv.shadow_owned_yes


def test_directional_inventory_is_yes_minus_no_on_shadow_basis() -> None:
    inv = build_inventory()
    assert inv.directional_inventory == Decimal("10")  # 17 - 7


def test_net_no_inventory_is_negative_d() -> None:
    inv = InventoryState(no_free=Decimal("8"), yes_free=Decimal("3"))
    assert inv.directional_inventory == Decimal("-5")


def test_mergeable_set_quantity_is_min_yes_no() -> None:
    inv = build_inventory()
    assert inv.mergeable_set_quantity == Decimal("7")  # min(17, 7)


def test_worst_case_terminal_value_uses_min_not_notional() -> None:
    inv = build_inventory()
    # W_min = C + min(Y, N) = 118.44 + 7
    assert inv.worst_case_terminal_value == Decimal("125.44")
    # resolution-conditional values
    assert inv.value_if_yes_resolves == Decimal("135.44")  # 118.44 + 17
    assert inv.value_if_no_resolves == Decimal("125.44")  # 118.44 + 7
