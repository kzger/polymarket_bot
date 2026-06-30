from __future__ import annotations

from config.settings import Settings
from bot.position_tracker import PositionTracker
from strategies.base_strategy import Side, Signal


class RiskManager:
    """Gate for every limit order placement.

    validate() checks four rules in order and returns (approved, reason).
    Returning False means the signal must be dropped; the Trader must not
    call OrderManager for that signal.
    """

    def __init__(self, settings: Settings, position_tracker: PositionTracker) -> None:
        self._s = settings
        self._pt = position_tracker
        self._open_order_count: int = 0  # updated by OrderManager via set_open_order_count()

    def set_open_order_count(self, count: int) -> None:
        self._open_order_count = count

    def validate(self, signal: Signal, token_id: str) -> tuple[bool, str]:
        if signal.side == Side.HOLD:
            return False, "hold signal"

        if signal.size < self._s.min_order_size_usdc:
            return False, f"size {signal.size} below minimum {self._s.min_order_size_usdc}"

        position = self._pt.get_position(token_id)
        if position >= self._s.max_position_usdc:
            return False, f"position {position:.2f} at cap {self._s.max_position_usdc}"

        if self._open_order_count >= self._s.max_open_orders:
            return False, f"open orders {self._open_order_count} at limit {self._s.max_open_orders}"

        if self._pt.daily_loss >= self._s.max_daily_loss_usdc:
            return False, f"daily loss {self._pt.daily_loss:.2f} exceeded limit {self._s.max_daily_loss_usdc}"

        return True, "approved"
