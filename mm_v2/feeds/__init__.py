"""WS-A — read-only feeds (no creds).

Raw event capture (Contract #1, :mod:`mm_v2.feeds.recorder`), the single typed
decode boundary (Contract #1b, :mod:`mm_v2.feeds.events`), and L2 book
reconstruction. Downstream code consumes ``ParsedRecordedEvent`` and must never
re-parse ``raw_payload`` (PLAN §10).
"""

__all__: list[str] = []
