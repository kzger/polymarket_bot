"""Two-layer allocator enums (WS-B, pure) — PLAN §3.3, §4.3.

The exposure router decides economic *direction* (INCREASE_YES / DECREASE_YES);
the inventory transformer decides SPLIT / MERGE / REDEEM. SPLIT/MERGE are
delta-neutral (ΔD = 0) capital/inventory transforms, NOT directional legs — the
directional change is always owned by the trade leg.
"""

from __future__ import annotations

from enum import Enum


class ExposureDirection(Enum):
    """What the exposure router emits."""

    INCREASE_YES = "INCREASE_YES"
    DECREASE_YES = "DECREASE_YES"


class ExposureRoute(Enum):
    """A concrete directional leg the execution allocator can place."""

    BUY_YES = "BUY_YES"
    SELL_NO = "SELL_NO"
    BUY_NO = "BUY_NO"
    SELL_YES = "SELL_YES"


class InventoryTransform(Enum):
    """Delta-neutral inventory/capital transforms (ΔD = 0)."""

    SPLIT = "SPLIT"  # collateral → YES + NO
    MERGE = "MERGE"  # YES + NO → collateral
    REDEEM = "REDEEM"  # winning token → collateral after resolution


class CompositePlan(Enum):
    """Named composite plans (a directional leg + a transform). Extensible.

    The directional change is owned by the leg, never by the merge/split
    (PLAN §3.3).
    """

    BUY_NO_THEN_MERGE = "BUY_NO_THEN_MERGE"
    BUY_YES_THEN_MERGE = "BUY_YES_THEN_MERGE"
    SPLIT_THEN_SELL_NO = "SPLIT_THEN_SELL_NO"
    SPLIT_THEN_SELL_YES = "SPLIT_THEN_SELL_YES"


# Sign each route applies to directional inventory D = Y − N (PLAN §6):
#   U₊ (D up)   = Q(BUY_YES) + Q(SELL_NO)
#   U₋ (D down) = Q(BUY_NO)  + Q(SELL_YES)
ROUTE_DIRECTIONAL_SIGN: dict[ExposureRoute, int] = {
    ExposureRoute.BUY_YES: +1,
    ExposureRoute.SELL_NO: +1,
    ExposureRoute.BUY_NO: -1,
    ExposureRoute.SELL_YES: -1,
}
