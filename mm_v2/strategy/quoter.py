"""Passive quoter (deferred — M3+).

Emits only ``PassivePostOnlyOrderRequest`` (Contract #2). The reward quoter
solves ``max_s [reward_score(s) − markout_loss(s) − inventory_cost(s)]`` — never
mechanically parked at ``max_incentive_spread`` (PLAN §9 M3). Stub only.
"""

__all__: list[str] = []
