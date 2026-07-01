"""L2 book builder (WS-A).

Applies snapshot + per-asset price_change deltas, verifying each asset's book
against the per-change ``hash`` (Contract #1b). Marks gaps as ``UNSYNCED`` when
match order cannot be inferred (Market WS has no official monotonic sequence —
ordering is the locally assigned ``local_sequence``). Implementation deferred to
the recorder build.
"""

__all__: list[str] = []
