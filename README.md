# Polymarket RBI Bot

This repository now has two parts:

- `mm_v2/` is the planned clean rewrite: a Polymarket-native, passive market-making system driven by Polymarket market/user data.
- `strategies/`, `bot/`, `backtesting/`, and `deploy/` are retired legacy reference code for the original ETH-signal RBI bot.

`mm_v2/PLAN.md` is the authoritative specification. Read it before implementing new system code.

## Development Environment

- OS: Windows
- Python: 3.12+
- Python environment and command runner: `uv`
- Live Polymarket work: gated behind explicit credentials and M0 conformance in `mm_v2/PLAN.md`

Use `uv` for all Python work:

```powershell
uv venv
uv sync
uv run pytest
uv run python deploy/run_backtest.py
```

Do not use bare `python`, `pip`, or `pytest` for repository commands.

## Repository Layout

| Path | Status | Purpose |
|---|---|---|
| `mm_v2/PLAN.md` | Authoritative spec | Current plan for the Polymarket-native market maker. |
| `mm_v2/` | New work area | New implementation should be built here according to `PLAN.md`. |
| `strategies/` | Retired reference | Legacy MACD/RSI/CVD strategies. Do not extend for `mm_v2`. |
| `bot/` | Retired reference | Legacy order, position, risk, and trader loop code. |
| `backtesting/` | Retired reference | Legacy candle-based backtesting. |
| `data/` | Retired/reference utilities | Legacy Binance/Polymarket data helpers. |
| `tests/` | Legacy tests | Tests for retired legacy modules. |
| `suggestion*.md` | Design history | Review rounds that led to `mm_v2/PLAN.md`. |

## Current Direction

The old bot mixed Binance ETH/USDT technical signals with arbitrary Polymarket token execution. That signal/target mismatch is retired.

The new system is a clean `mm_v2/` implementation with these constraints:

- Binary Polymarket markets only for v1.
- YES/NO books are modeled together by `condition_id`.
- Inventory is fill-ledger derived, not mutable notional totals.
- Complete-set split/merge/redeem is core inventory functionality.
- Quotes are passive post-only orders.
- Risk uses directional unmatched limits plus paired inventory and pending-operation caps.
- Recorder, live handling, replay, ledger, and order state machine share event semantics.
- Frozen contracts in `mm_v2/PLAN.md` §10 must not be changed silently.

## Implementation Order

Workstreams that do not need credentials can start first:

1. WS-A: `feeds/` recorder, typed event decoder, book builder, public market/user read path.
2. WS-B: `domain/` pure inventory, order, market spec, routing, and risk model.
3. WS-C: `accounting/` markout and shadow replay inputs.

Credentialed work is gated:

4. WS-D: `execution/` adapters and `app/conformance_main.py` after explicit M0 authorization and credentials.

Before parallel work, follow the frozen contracts in `mm_v2/PLAN.md` §10:

- Contract #1: recorded event envelope
- Contract #1b: parsed event union and decode boundary
- Contract #2: `ExchangePort` / `CtfPort`
- Contract #3: inventory balance basis
- Contract #4: settlement identity

## Commands

Create and sync the environment:

```powershell
uv venv
uv sync
```

Run tests:

```powershell
uv run pytest
```

Run legacy backtest tooling when needed for reference only:

```powershell
uv run python deploy/run_backtest.py
```

## Configuration

Use `.env.example` as a template. Do not commit real credentials.

Live `mm_v2` work requires explicit user authorization and the M0 credential set described in `mm_v2/PLAN.md` §12. Type-3 deposit-wallet order placement remains an SDK/protocol-stack gate in M0; do not assume any client path works until conformance proves it.

## New Session Prompt

Use this prompt to start an implementation session:

```text
You are implementing the Polymarket-native mm_v2 system in this repo.

First read AGENTS.md, CLAUDE.md, README.md, and mm_v2/PLAN.md fully. Treat mm_v2/PLAN.md as the single source of truth. Do not redesign the strategy direction and do not modify legacy directories unless explicitly asked.

Important constraints:
- Use uv for all Python environment creation and execution: uv venv, uv sync, uv run pytest, uv run python ...
- The legacy strategies/, bot/, backtesting/, deploy/ code is retired reference only.
- Frozen contracts in mm_v2/PLAN.md §10 must be implemented exactly: Contract #1 RecordedEvent, #1b ParsedRecordedEvent/decode_recorded_event, #2 ExchangePort/CtfPort, #3 inventory balance basis, #4 settlement identity.
- If any external fact conflicts with PLAN.md, add a proposal to §11 Open decisions instead of silently diverging in code.
- No live trading or credential use unless the task explicitly enters M0 or M2.5 and credentials are provided.

Start with no-credential work:
1. Build mm_v2 package skeleton for WS-A/WS-B/WS-C.
2. Implement typed contract models and pure domain types first.
3. Add focused tests for inventory math, reachable risk interval, parsed market/user events, WS-vs-REST trade identity, and post-only request invariants.
4. Run uv run pytest and report exact results.

Keep changes scoped and report modified files plus verification output.
```

## Reference Files

- `mm_v2/PLAN.md`: authoritative implementation plan.
- `suggestion.md`, `suggestion2.md`, `suggestion3.md`: design discussion history.
- `polymarket_requirement.md`: original requirements notes.

## License

MIT
