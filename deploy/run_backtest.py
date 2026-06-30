"""Entry point: run a parallel backtest parameter sweep and print metrics."""

from dotenv import load_dotenv

load_dotenv()

import pandas as pd

from config.settings import Settings
from data.downloader import fetch_recent_candles
from data.storage import load_candles, save_candles
from strategies.macd_strategy import MACDStrategy
from strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from backtesting.runner import run_parallel


_PARAM_GRIDS = {
    MACDStrategy: [
        {"fast_period": 3, "slow_period": 15, "signal_period": 3, "size": 10.0},
        {"fast_period": 5, "slow_period": 20, "signal_period": 5, "size": 10.0},
        {"fast_period": 8, "slow_period": 21, "signal_period": 5, "size": 10.0},
    ],
    RSIMeanReversionStrategy: [
        {"rsi_period": 14, "oversold": 30.0, "overbought": 70.0, "size": 10.0},
        {"rsi_period": 10, "oversold": 25.0, "overbought": 75.0, "size": 10.0},
        {"rsi_period": 21, "oversold": 35.0, "overbought": 65.0, "size": 10.0},
    ],
}


def main() -> None:
    settings = Settings()

    print(f"[Backtest] Fetching candles: {settings.binance_symbol} {settings.candle_interval}")
    candles = fetch_recent_candles(
        symbol=settings.binance_symbol,
        interval=settings.candle_interval,
        n=1000,
    )
    save_candles(candles, settings.binance_symbol, settings.candle_interval, settings.storage_backend)
    print(f"[Backtest] Loaded {len(candles)} candles")

    all_results = []
    for strategy_class, param_grid in _PARAM_GRIDS.items():
        print(f"\n[Backtest] Running {strategy_class.__name__} ({len(param_grid)} param sets)...")
        results = run_parallel(strategy_class, param_grid, candles, settings)
        all_results.append(results)

    combined = pd.concat(all_results, ignore_index=True).sort_values("sharpe_ratio", ascending=False)

    print("\n=== Backtest Results (sorted by Sharpe) ===")
    cols = ["strategy", "params", "total_trades", "win_rate", "profit_factor", "sharpe_ratio", "max_drawdown", "total_pnl"]
    print(combined[[c for c in cols if c in combined.columns]].to_string(index=False))


if __name__ == "__main__":
    main()
