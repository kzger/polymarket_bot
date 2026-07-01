"""User WebSocket read path (WS-A / gated).

Subscribes to the User channel (order placement/update/cancel, trade
MATCHED→MINED→CONFIRMED/FAILED with the non-terminal RETRYING loop). WS frames
carry no bucket/transaction metadata (Contract #1b / #4); settlement buckets
arrive only via the REST trades endpoint. Implementation deferred.
"""

__all__: list[str] = []
