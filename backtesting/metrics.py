from __future__ import annotations

import numpy as np
import pandas as pd


def win_rate(trade_log: pd.DataFrame) -> float:
    if trade_log.empty:
        return 0.0
    wins = (trade_log["pnl"] > 0).sum()
    return float(wins / len(trade_log))


def profit_factor(trade_log: pd.DataFrame) -> float:
    if trade_log.empty:
        return 0.0
    gross_profit = trade_log.loc[trade_log["pnl"] > 0, "pnl"].sum()
    gross_loss = abs(trade_log.loc[trade_log["pnl"] < 0, "pnl"].sum())
    return float(gross_profit / gross_loss) if gross_loss > 0 else float("inf")


def sharpe_ratio(trade_log: pd.DataFrame, periods_per_year: int = 105120) -> float:
    """Annualised Sharpe ratio. periods_per_year=105120 assumes 5-min candles."""
    if trade_log.empty or len(trade_log) < 2:
        return 0.0
    returns = trade_log["pnl"] / (trade_log["size"] + 1e-9)
    mean_r = returns.mean()
    std_r = returns.std()
    if std_r == 0:
        return 0.0
    return float(mean_r / std_r * np.sqrt(periods_per_year))


def max_drawdown(trade_log: pd.DataFrame) -> float:
    if trade_log.empty:
        return 0.0
    cumulative = trade_log["pnl"].cumsum()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max).min()
    return float(drawdown)


def summary(trade_log: pd.DataFrame) -> dict:
    return {
        "total_trades": len(trade_log),
        "win_rate": round(win_rate(trade_log), 4),
        "profit_factor": round(profit_factor(trade_log), 4),
        "sharpe_ratio": round(sharpe_ratio(trade_log), 4),
        "max_drawdown": round(max_drawdown(trade_log), 4),
        "total_pnl": round(float(trade_log["pnl"].sum()) if not trade_log.empty else 0.0, 4),
    }
