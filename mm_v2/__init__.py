"""mm_v2 — Polymarket-native, passive market-making system.

This package is the clean rewrite described in ``mm_v2/PLAN.md`` (the single
source of truth). The legacy ``strategies/``, ``bot/``, ``backtesting/`` and
``deploy/`` packages are retired reference code and are not imported here.

Workstreams (PLAN §10):

* WS-A (``feeds/``)      — recorder, decode boundary, book builder. No creds.
* WS-B (``domain/``)     — pure inventory / order / routing / risk. No creds.
* WS-C (``accounting/``) — markout + shadow engine. No creds.
* WS-D (``execution/``)  — live adapters. **Gated on credentials + M0.**

Frozen contracts live where they are consumed:

* Contract #1  — :mod:`mm_v2.feeds.recorder` (``RecordedEvent`` envelope).
* Contract #1b — :mod:`mm_v2.feeds.events` (``ParsedRecordedEvent`` + decode).
* Contract #2  — :mod:`mm_v2.execution.exchange_port` / ``ctf_port``.
* Contract #3  — :mod:`mm_v2.domain.inventory` (balance basis).
* Contract #4  — :mod:`mm_v2.domain.fill` (settlement identity).
"""

__all__: list[str] = []
