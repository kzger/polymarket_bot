"""WS-D — execution adapters (CREDENTIALED, gated on M0 authorization).

Only the *interfaces* (Contract #2: :mod:`mm_v2.execution.exchange_port` and
:mod:`mm_v2.execution.ctf_port`) and pure request/result value objects live
here today. Concrete adapters (``clob_adapter``, ``order_state_machine``,
``reconciler``) are stubs until M0 credentials + protocol-stack selection
(PLAN §8, §11, §12). Domain/strategy/risk depend only on the typed ports.
"""

__all__: list[str] = []
