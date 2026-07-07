# AGENTS.md

This file records Codex-specific operating rules. For project overview, commands, and implementation order, use:

@README.md

## Codex Specific Settings

- Use `uv` for all Python environment creation and command execution. Do not use bare `python`, `pip`, or `pytest` for repo work.
- Preferred commands:
  - `uv venv`
  - `uv sync`
  - `uv run pytest`
  - `uv run python <script>`
- Treat `mm_v2/PLAN.md` as the authoritative specification for the new Polymarket-native market-making system.
- The retired legacy ETH-signal bot (`strategies/`, `bot/`, `backtesting/`, `deploy/`, `data/`, `config/`, `incubation/`, `tests/`) has been removed; `mm_v2/` is the only implementation.
- Do not silently diverge from frozen contracts in `mm_v2/PLAN.md` §10. If a contract needs to change, propose it in §11 first.
- Keep scratch notes and generated work-in-progress artifacts under `agent_workspace/for_codex/`.
- Do not commit `.env`, `.venv`, `.pytest_cache`, `__pycache__`, `.serena`, `.codegraph`, crash dumps, downloaded market data, or credentials.
- Do not revert unrelated dirty worktree changes. Treat existing changes as user-owned unless the user explicitly asks to revert them.
