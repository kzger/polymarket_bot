from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timezone

from data import storage


class PositionTracker:
    """Tracks open positions and running P&L per Polymarket token.

    State is kept in memory and flushed to logs/positions.json on every update
    so the monitor process can read it without an inter-process queue.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._positions: dict[str, float] = defaultdict(float)   # token_id -> USDC value
        self._pnl: dict[str, float] = defaultdict(float)         # token_id -> realised P&L
        self._daily_loss: float = 0.0
        self._daily_reset_date: str = self._today()

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _check_daily_reset(self) -> None:
        if self._today() != self._daily_reset_date:
            self._daily_loss = 0.0
            self._daily_reset_date = self._today()

    def update_fill(self, token_id: str, side: str, price: float, size: float) -> None:
        with self._lock:
            self._check_daily_reset()
            notional = price * size
            if side == "BUY":
                self._positions[token_id] += notional
            else:
                prev = self._positions.get(token_id, 0.0)
                realised = notional - prev
                self._pnl[token_id] += realised
                if realised < 0:
                    self._daily_loss += abs(realised)
                self._positions[token_id] = max(0.0, prev - notional)
            self._persist()

    def get_position(self, token_id: str) -> float:
        with self._lock:
            return self._positions.get(token_id, 0.0)

    def get_pnl(self, token_id: str) -> float:
        with self._lock:
            return self._pnl.get(token_id, 0.0)

    @property
    def daily_loss(self) -> float:
        with self._lock:
            self._check_daily_reset()
            return self._daily_loss

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "positions": dict(self._positions),
                "pnl": dict(self._pnl),
                "daily_loss": self._daily_loss,
                "date": self._daily_reset_date,
            }

    def _persist(self) -> None:
        storage.save_positions(self.snapshot())
