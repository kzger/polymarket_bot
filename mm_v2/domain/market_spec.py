"""MarketSpec (WS-B, pure) — PLAN §4.1.

Per-condition static/semi-static market definition. The data primary key is
``condition_id → {yes_token_id, no_token_id}``; we always reason about both
books (core invariant #1). ``tick_size`` may change live → requote on a
tick-size-change event. Collateral is abstracted (never hard-coded as USDC).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from mm_v2.domain.order import Outcome


@dataclass(frozen=True, slots=True)
class RewardParams:
    """Liquidity-reward qualification parameters (PLAN §8)."""

    min_incentive_size: Decimal | None = None
    max_incentive_spread: Decimal | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MarketSpec:
    condition_id: str
    yes_token_id: str
    no_token_id: str
    collateral_asset: str
    tick_size: Decimal
    neg_risk: bool = False  # v1: binary only; field kept for later
    fees_enabled: bool = False
    fee_schedule: Mapping[str, Any] | None = None
    reward_params: RewardParams | None = None
    market_status: str = "unknown"

    def outcome_for_asset(self, asset_id: str) -> Outcome | None:
        """Map a token id back to its outcome, or ``None`` if it is neither.

        Risk / routing must reason about both books, so they resolve an
        ``asset_id`` to YES/NO through the spec rather than guessing.
        """
        if asset_id == self.yes_token_id:
            return Outcome.YES
        if asset_id == self.no_token_id:
            return Outcome.NO
        return None
