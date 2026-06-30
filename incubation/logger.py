from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from strategies.base_strategy import Signal


_LOG_DIR = Path("logs")


class TradeLogger:
    """Thread-safe JSON-lines logger for trade events and signals."""

    def __init__(self, log_file: str = "trades.jsonl") -> None:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._path = _LOG_DIR / log_file
        self._lock = threading.Lock()

    def _write(self, event: dict) -> None:
        event["ts"] = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")

    def log_signal(self, token_id: str, signal: Signal, approved: bool, reason: str) -> None:
        self._write({
            "type": "signal",
            "token_id": token_id,
            "strategy": signal.strategy_name,
            "side": signal.side.value,
            "price": signal.price,
            "size": signal.size,
            "confidence": round(signal.confidence, 4),
            "approved": approved,
            "reason": reason,
        })

    def log_fill(self, token_id: str, order_id: str, side: str, price: float, size: float) -> None:
        self._write({
            "type": "fill",
            "token_id": token_id,
            "order_id": order_id,
            "side": side,
            "price": price,
            "size": size,
        })

    def log_error(self, context: str, exc: Exception) -> None:
        self._write({
            "type": "error",
            "context": context,
            "error": str(exc),
        })
