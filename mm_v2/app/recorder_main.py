"""M0.5 recorder entry point (read-only, no creds).

Captures raw Market WS frames + periodic REST snapshots as Contract #1
``RecordedEvent`` records, with reconnect/unsynced markers and the
latency-calibrated shadow-markout pipeline (PLAN §7). Wiring deferred until the
feeds read path is built. Stub only.
"""

__all__: list[str] = []


def main() -> None:  # pragma: no cover - entry point stub
    raise NotImplementedError("Recorder entry point not yet implemented (M0.5).")
