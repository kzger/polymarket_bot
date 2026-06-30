from __future__ import annotations

from datetime import datetime, timezone


class Scaler:
    """Gradually ramps position size from seed_size to full_size over ramp_days.

    Used during incubation to limit initial exposure while a new strategy
    establishes a live track record.

    Example:
        scaler = Scaler(seed_size=2.0, full_size=10.0, ramp_days=14)
        # On day 7 of live trading, get_current_size() returns ~6.0
    """

    def __init__(
        self,
        seed_size: float = 2.0,
        full_size: float = 10.0,
        ramp_days: int = 14,
    ) -> None:
        self._seed = seed_size
        self._full = full_size
        self._ramp_days = ramp_days
        # Track per-strategy start dates
        self._start_dates: dict[str, datetime] = {}

    def start(self, strategy_name: str) -> None:
        """Record the live start date for a strategy."""
        if strategy_name not in self._start_dates:
            self._start_dates[strategy_name] = datetime.now(timezone.utc)

    def get_current_size(self, strategy_name: str) -> float:
        """Return the current allowed position size for a strategy."""
        if strategy_name not in self._start_dates:
            self.start(strategy_name)

        now = datetime.now(timezone.utc)
        days_live = (now - self._start_dates[strategy_name]).total_seconds() / 86400
        progress = min(days_live / self._ramp_days, 1.0)
        return round(self._seed + (self._full - self._seed) * progress, 2)
