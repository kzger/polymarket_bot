from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pandas as pd


_DATA_DIR = Path("data/candles")
_LOG_DIR = Path("logs")


def _ensure_dirs() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def _csv_path(symbol: str, interval: str) -> Path:
    safe_symbol = symbol.replace("/", "_")
    return _DATA_DIR / f"{safe_symbol}_{interval}.csv"


def _db_path() -> Path:
    return _DATA_DIR / "candles.db"


def save_candles(df: pd.DataFrame, symbol: str, interval: str, backend: str = "csv") -> None:
    _ensure_dirs()
    if backend == "sqlite":
        table = f"{symbol.replace('/', '_')}_{interval}"
        with sqlite3.connect(_db_path()) as conn:
            df.to_sql(table, conn, if_exists="append", index=True)
    else:
        path = _csv_path(symbol, interval)
        df.to_csv(path, mode="a", header=not path.exists())


def load_candles(
    symbol: str,
    interval: str,
    start: str | None = None,
    end: str | None = None,
    backend: str = "csv",
) -> pd.DataFrame:
    _ensure_dirs()
    if backend == "sqlite":
        table = f"{symbol.replace('/', '_')}_{interval}"
        with sqlite3.connect(_db_path()) as conn:
            df = pd.read_sql(f"SELECT * FROM {table}", conn, index_col="timestamp", parse_dates=["timestamp"])
    else:
        path = _csv_path(symbol, interval)
        if not path.exists():
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.read_csv(path, index_col="timestamp", parse_dates=["timestamp"])

    if start:
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        df = df[df.index <= pd.Timestamp(end, tz="UTC")]
    return df.sort_index().drop_duplicates()


def save_trade_log(event: dict) -> None:
    _ensure_dirs()
    log_path = _LOG_DIR / "trades.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def save_positions(positions: dict) -> None:
    _ensure_dirs()
    pos_path = _LOG_DIR / "positions.json"
    with open(pos_path, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)


def load_positions() -> dict:
    pos_path = _LOG_DIR / "positions.json"
    if not pos_path.exists():
        return {}
    with open(pos_path, encoding="utf-8") as f:
        return json.load(f)
