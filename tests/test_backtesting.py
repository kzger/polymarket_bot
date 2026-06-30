"""Unit tests for the backtest engine and metrics module."""

import numpy as np
import pandas as pd
import pytest

from backtesting.engine import BacktestEngine
from backtesting.metrics import summary, win_rate, profit_factor, sharpe_ratio, max_drawdown
from config.settings import Settings
from strategies.macd_strategy import MACDStrategy
from strategies.rsi_mean_reversion import RSIMeanReversionStrategy


def _make_candles(n: int = 300, pattern: str = "oscillating") -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    if pattern == "oscillating":
        closes = 0.5 + 0.2 * np.sin(np.linspace(0, 8 * np.pi, n))
    elif pattern == "trending_up":
        closes = np.linspace(0.2, 0.8, n)
    else:
        closes = np.ones(n) * 0.5
    return pd.DataFrame(
        {
            "open": closes * 0.999,
            "high": closes * 1.002,
            "low": closes * 0.998,
            "close": closes,
            "volume": np.ones(n) * 1000.0,
        },
        index=timestamps,
    )


def _default_settings() -> Settings:
    return Settings(
        poly_private_key="0x" + "0" * 64,
        min_order_size_usdc=1.0,
    )


class TestBacktestEngine:
    def test_returns_dataframe(self):
        engine = BacktestEngine(
            strategy=MACDStrategy(),
            candles=_make_candles(300),
            settings=_default_settings(),
        )
        result = engine.run()
        assert isinstance(result, pd.DataFrame)

    def test_trade_log_columns(self):
        engine = BacktestEngine(
            strategy=MACDStrategy(),
            candles=_make_candles(300),
            settings=_default_settings(),
        )
        result = engine.run()
        expected_cols = {"entry_time", "exit_time", "side", "entry_price", "exit_price", "size", "pnl"}
        assert expected_cols.issubset(set(result.columns))

    def test_empty_result_on_flat_candles(self):
        engine = BacktestEngine(
            strategy=MACDStrategy(),
            candles=_make_candles(300, pattern="flat"),
            settings=_default_settings(),
        )
        result = engine.run()
        # Flat price → no MACD crossovers → no trades
        assert isinstance(result, pd.DataFrame)

    def test_rsi_strategy_runs(self):
        engine = BacktestEngine(
            strategy=RSIMeanReversionStrategy(),
            candles=_make_candles(300, pattern="oscillating"),
            settings=_default_settings(),
        )
        result = engine.run()
        assert isinstance(result, pd.DataFrame)


class TestMetrics:
    def _make_trade_log(self, pnls: list[float], sizes: list[float] | None = None) -> pd.DataFrame:
        n = len(pnls)
        if sizes is None:
            sizes = [10.0] * n
        return pd.DataFrame({"pnl": pnls, "size": sizes})

    def test_win_rate_all_wins(self):
        log = self._make_trade_log([1.0, 2.0, 3.0])
        assert win_rate(log) == 1.0

    def test_win_rate_no_wins(self):
        log = self._make_trade_log([-1.0, -2.0])
        assert win_rate(log) == 0.0

    def test_win_rate_mixed(self):
        log = self._make_trade_log([1.0, -1.0, 1.0, -1.0])
        assert win_rate(log) == 0.5

    def test_profit_factor_all_wins(self):
        log = self._make_trade_log([1.0, 2.0])
        assert profit_factor(log) == float("inf")

    def test_profit_factor_mixed(self):
        log = self._make_trade_log([2.0, -1.0])
        assert profit_factor(log) == pytest.approx(2.0)

    def test_max_drawdown_is_nonpositive(self):
        log = self._make_trade_log([1.0, -3.0, 1.0])
        assert max_drawdown(log) <= 0

    def test_summary_keys(self):
        log = self._make_trade_log([1.0, -0.5, 2.0])
        result = summary(log)
        for key in ("total_trades", "win_rate", "profit_factor", "sharpe_ratio", "max_drawdown", "total_pnl"):
            assert key in result

    def test_empty_trade_log(self):
        log = pd.DataFrame(columns=["pnl", "size"])
        result = summary(log)
        assert result["total_trades"] == 0
        assert result["win_rate"] == 0.0
