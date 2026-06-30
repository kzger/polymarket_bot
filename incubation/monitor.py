from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path


_POSITIONS_FILE = Path("logs/positions.json")
_TRADES_FILE = Path("logs/trades.jsonl")


def _load_positions() -> dict:
    if not _POSITIONS_FILE.exists():
        return {}
    with open(_POSITIONS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _load_recent_signals(n: int = 10) -> list[dict]:
    if not _TRADES_FILE.exists():
        return []
    lines = _TRADES_FILE.read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line) for line in lines[-n:] if line]
    return [e for e in events if e.get("type") == "signal"]


def _print_dashboard(positions: dict, signals: list[dict]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print("\033[2J\033[H", end="")  # clear terminal
    print(f"=== Polymarket Bot Monitor  [{now}] ===\n")

    pos_data = positions.get("positions", {})
    pnl_data = positions.get("pnl", {})
    daily_loss = positions.get("daily_loss", 0.0)

    print(f"{'Token ID':<50} {'Position (USDC)':>16} {'P&L':>10}")
    print("-" * 80)
    if pos_data:
        for token_id, pos in pos_data.items():
            pnl = pnl_data.get(token_id, 0.0)
            print(f"{token_id:<50} {pos:>16.2f} {pnl:>+10.2f}")
    else:
        print("  (no open positions)")

    print(f"\nDaily Loss: ${daily_loss:.2f}")
    print(f"\n--- Last {len(signals)} Signals ---")
    for s in reversed(signals):
        status = "OK " if s.get("approved") else "REJ"
        print(
            f"[{status}] {s.get('ts', '')[:19]}  {s.get('token_id', '')[:20]:<22}"
            f"  {s.get('side', ''):4}  @ {s.get('price', 0):.4f}"
            f"  size={s.get('size', 0):.2f}  conf={s.get('confidence', 0):.2f}"
            f"  [{s.get('reason', '')}]"
        )


def run(interval_seconds: int = 30) -> None:
    """Start the monitoring dashboard loop."""
    print("Starting monitor... (Ctrl+C to stop)")
    while True:
        positions = _load_positions()
        signals = _load_recent_signals(n=10)
        _print_dashboard(positions, signals)
        time.sleep(interval_seconds)
