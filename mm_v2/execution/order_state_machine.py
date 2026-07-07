"""Order lifecycle state machine (WS-D).

Drives INTENT → PENDING_NEW → LIVE → PARTIALLY_FILLED → FILLED with
PENDING_CANCEL → CANCELED, any → REJECTED, and any → UNKNOWN (lost
response/timeout) → reconcile → resolved (PLAN §4.4). A timeout must yield
``UNKNOWN``, never an exception-only result (Contract #2). Implementation
deferred to WS-D.
"""

__all__: list[str] = []
