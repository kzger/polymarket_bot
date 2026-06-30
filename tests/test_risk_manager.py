"""Unit tests for RiskManager — each rule tested in isolation."""

import pytest

from bot.risk_manager import RiskManager
from bot.position_tracker import PositionTracker
from config.settings import Settings
from strategies.base_strategy import Side, Signal


def _make_settings(**overrides) -> Settings:
    defaults = dict(
        poly_private_key="0x" + "0" * 64,
        max_position_usdc=500.0,
        max_daily_loss_usdc=100.0,
        max_open_orders=10,
        min_order_size_usdc=1.0,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _make_signal(side=Side.BUY, price=0.5, size=10.0, confidence=0.8) -> Signal:
    return Signal(side=side, price=price, size=size, confidence=confidence, strategy_name="test")


class TestRiskManagerRules:
    def setup_method(self):
        self.settings = _make_settings()
        self.tracker = PositionTracker()
        self.rm = RiskManager(self.settings, self.tracker)

    def test_hold_signal_is_rejected(self):
        signal = _make_signal(side=Side.HOLD)
        approved, reason = self.rm.validate(signal, "token_1")
        assert not approved
        assert "hold" in reason.lower()

    def test_below_minimum_size_is_rejected(self):
        signal = _make_signal(size=0.5)
        approved, reason = self.rm.validate(signal, "token_1")
        assert not approved
        assert "minimum" in reason.lower()

    def test_valid_signal_is_approved(self):
        signal = _make_signal(size=10.0)
        approved, reason = self.rm.validate(signal, "token_1")
        assert approved
        assert reason == "approved"

    def test_position_cap_blocks_order(self):
        # Simulate existing position at cap
        self.tracker.update_fill("token_1", "BUY", 0.5, 1000.0)  # $500 position
        signal = _make_signal()
        approved, reason = self.rm.validate(signal, "token_1")
        assert not approved
        assert "cap" in reason.lower()

    def test_open_order_limit_blocks_order(self):
        self.rm.set_open_order_count(10)
        signal = _make_signal()
        approved, reason = self.rm.validate(signal, "token_1")
        assert not approved
        assert "limit" in reason.lower()

    def test_daily_loss_halt(self):
        # Simulate losses exceeding threshold
        self.tracker.update_fill("token_1", "BUY", 0.5, 200.0)   # buy
        self.tracker.update_fill("token_1", "SELL", 0.1, 200.0)   # sell at a loss → daily_loss increases
        # Force daily_loss over threshold
        self.settings = _make_settings(max_daily_loss_usdc=0.01)
        self.rm = RiskManager(self.settings, self.tracker)
        # Re-apply loss
        self.tracker.update_fill("token_2", "BUY", 0.5, 10.0)
        self.tracker.update_fill("token_2", "SELL", 0.1, 10.0)
        signal = _make_signal()
        approved, reason = self.rm.validate(signal, "token_3")
        assert not approved
        assert "daily loss" in reason.lower()

    def test_sell_signal_is_approved(self):
        signal = _make_signal(side=Side.SELL, price=0.6)
        approved, reason = self.rm.validate(signal, "token_1")
        assert approved

    def test_exact_minimum_size_is_approved(self):
        signal = _make_signal(size=1.0)
        approved, reason = self.rm.validate(signal, "token_1")
        assert approved
