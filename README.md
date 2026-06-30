# Polymarket RBI Trading Bot

A Python algorithmic trading bot for Polymarket's prediction market CLOB. Uses three technical strategies (MACD, RSI+VWAP, CVD) with a polling-based execution loop, full backtesting support, and a risk-controlled order layer. All orders are **limit orders only** via `py-clob-client`.

---

## Project Structure

```
polymarket-rbi-bot/
├── config/
│   ├── settings.py          # All parameters (Pydantic, loaded from .env)
│   └── accounts.py          # Polymarket account setup
├── data/
│   ├── downloader.py        # Binance OHLCV via ccxt
│   ├── polymarket_client.py # Polymarket CLOB API wrapper
│   └── storage.py           # CSV / SQLite persistence
├── strategies/
│   ├── base_strategy.py     # BaseStrategy ABC + Signal / MarketData types
│   ├── macd_strategy.py     # MACD Histogram (3/15/3)
│   ├── rsi_mean_reversion.py# RSI(14) Mean Reversion + VWAP filter
│   └── cvd_strategy.py      # Cumulative Volume Delta divergence
├── backtesting/
│   ├── engine.py            # Tick-by-tick backtest engine
│   ├── metrics.py           # Win rate, profit factor, Sharpe, drawdown
│   └── runner.py            # Parallel parameter sweep
├── bot/
│   ├── trader.py            # 5-minute polling loop + strategy registry
│   ├── risk_manager.py      # Position cap, open orders, daily loss, min size
│   ├── order_manager.py     # Limit order lifecycle + deduplication
│   └── position_tracker.py  # Position and P&L per market
├── incubation/
│   ├── monitor.py           # Live P&L dashboard
│   ├── scaler.py            # Gradual position size ramp
│   └── logger.py            # JSON-lines trade event logger
├── deploy/
│   ├── run_bot.py           # Launch live bot
│   ├── run_backtest.py      # Launch backtest + print metrics
│   └── run_monitor.py       # Launch incubation monitor
└── tests/
    ├── test_strategies.py
    ├── test_backtesting.py
    └── test_risk_manager.py
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your Polymarket private key and API credentials
```

### 3. Run a backtest

```bash
python deploy/run_backtest.py
```

### 4. Run the live bot (dry-run: set MAX_POSITION_USDC=0 in .env)

```bash
python deploy/run_bot.py
```

### 5. Launch the monitor in a separate terminal

```bash
python deploy/run_monitor.py
```

---

## Strategies

| Strategy | Signal Logic | Data Source |
|----------|-------------|-------------|
| **MACD** | Histogram zero-cross (fast=3, slow=15, signal=3) | Binance OHLCV |
| **RSI Mean Reversion** | RSI(14) < 30 / > 70 with VWAP filter | Binance OHLCV |
| **CVD** | Bid/ask size delta divergence from price | Polymarket order book |

Signals are combined via majority vote, with price averaged by confidence weight.

---

## Risk Controls

- **Max position per market**: configurable USDC cap (default $500)
- **Max open orders**: cap on resting limit orders (default 10)
- **Max daily loss**: halt trading at threshold (default $100)
- **Min order size**: reject signals below Polymarket minimum (default $1)

---

## Backtesting

The `BacktestEngine` reuses the same `BaseStrategy` objects as the live bot — no adapter layer.
Limit orders are simulated: BUY fills when the next candle's low touches the limit price; SELL fills when the high touches it. Unfilled orders expire after 3 candles.

Run a parallel parameter sweep:

```bash
python deploy/run_backtest.py
```

---

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `POLY_PRIVATE_KEY` | — | Polymarket wallet private key |
| `POLY_HOST` | `https://clob.polymarket.com` | CLOB API endpoint |
| `BINANCE_SYMBOL` | `ETH/USDT` | ccxt symbol for OHLCV data |
| `MAX_POSITION_USDC` | `500` | Max exposure per market |
| `MAX_DAILY_LOSS_USDC` | `100` | Daily loss halt threshold |
| `POLL_INTERVAL_SECONDS` | `300` | Bot loop interval (5 min) |

---

## License

MIT
