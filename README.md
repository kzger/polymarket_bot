# Polymarket RBI Bot

`mm_v2/` is the system: a Polymarket-native, passive market-making implementation driven by Polymarket market/user data. The original ETH-signal RBI bot (`strategies/`, `bot/`, `backtesting/`, `deploy/`, `data/`, `config/`, `incubation/`, `tests/`) has been removed;

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
```

Do not use bare `python`, `pip`, or `pytest` for repository commands.

## Repository Layout

| Path | Status | Purpose |
|---|---|---|
| `mm_v2/PLAN.md` | Authoritative spec | Current plan for the Polymarket-native market maker. |
| `mm_v2/` | Implementation | The system, built according to `PLAN.md`. Tests live in `mm_v2/tests/`. |

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

## Configuration

Use `.env.example` as a template. Do not commit real credentials.

Live `mm_v2` work requires explicit user authorization and the M0 credential set described in `mm_v2/PLAN.md` §12. Type-3 deposit-wallet order placement remains an SDK/protocol-stack gate in M0; do not assume any client path works until conformance proves it.

## Reference Files

- `mm_v2/PLAN.md`: authoritative implementation plan.

## License

MIT
