"""CLOB adapter (WS-D — CREDENTIALED, gated).

Concrete :class:`~mm_v2.execution.exchange_port.ExchangePort` implementation.
The protocol stack is UNDECIDED (PLAN §11): py-sdk / py-clob-client-v2 / ts-sdk
/ rs-clob-client-v2 / direct REST — none has a known-good type-3 path today
(issue #70). Selection happens empirically in the M0 conformance harness. Do
not implement until M0 authorization + credentials are provided.
"""

__all__: list[str] = []
