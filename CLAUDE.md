# CLAUDE.md

This file records Claude Code-specific settings. For project overview, commands, and implementation order, use:

@README.md

## Claude Code Specific Settings

- Use Plan Mode before broad architecture changes, frozen-contract changes, live trading / credential work, or changes to risk/accounting semantics.
- Use `uv` for all Python environment creation and command execution.
- Read `mm_v2/PLAN.md` fully before implementing `mm_v2/` code. It is the single source of truth.
- Keep live trading work gated. Do not request or use credentials unless the task explicitly enters M0 / M2.5 live conformance work.
