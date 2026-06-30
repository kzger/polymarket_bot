from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

import pandas as pd

from backtesting.engine import BacktestEngine
from backtesting.metrics import summary
from config.settings import Settings


def _run_single(args: tuple) -> dict:
    strategy_class, params, candles, settings_dict = args
    settings = Settings(**settings_dict)
    strategy = strategy_class(**params)
    engine = BacktestEngine(strategy=strategy, candles=candles, settings=settings)
    trade_log = engine.run()
    result = summary(trade_log)
    result["params"] = params
    result["strategy"] = strategy_class.__name__
    return result


def run_parallel(
    strategy_class: type,
    param_grid: list[dict[str, Any]],
    candles: pd.DataFrame,
    settings: Settings,
    max_workers: int = 4,
) -> pd.DataFrame:
    """Run a parameter sweep in parallel. Returns results sorted by Sharpe ratio.

    Example:
        results = run_parallel(
            MACDStrategy,
            param_grid=[
                {"fast_period": 3, "slow_period": 15, "signal_period": 3},
                {"fast_period": 5, "slow_period": 20, "signal_period": 5},
            ],
            candles=candles,
            settings=settings,
        )
    """
    settings_dict = settings.model_dump()

    tasks = [(strategy_class, params, candles, settings_dict) for params in param_grid]

    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_single, task): task for task in tasks}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                params = futures[future][1]
                results.append({"params": params, "error": str(exc), "sharpe_ratio": float("-inf")})

    df = pd.DataFrame(results).sort_values("sharpe_ratio", ascending=False).reset_index(drop=True)
    return df
