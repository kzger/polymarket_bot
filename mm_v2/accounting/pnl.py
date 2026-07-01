"""Three-bucket P&L (WS-C).

Attributes P&L into ``core_trading_pnl`` / ``maker_rebate`` /
``liquidity_reward``. Rewards may never mask a negative spread-after-markout;
core and subsidy are reported separately (PLAN §3.9). Stub for now.
"""

__all__: list[str] = []
