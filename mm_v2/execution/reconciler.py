"""Order/settlement reconciler (WS-D).

Resolves ``UNKNOWN`` orders via REST open-orders/trades + user WS, and promotes
logical fills to settlement only when all settlement buckets are terminal
(Contract #4). Owns the age-based reconcile/breaker for the RETRYING loop
(PLAN §3.2). Implementation deferred to WS-D.
"""

__all__: list[str] = []
