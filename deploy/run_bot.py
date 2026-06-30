"""Entry point: start the live trading bot."""

from dotenv import load_dotenv

load_dotenv()

from config.settings import Settings
from config.accounts import load_accounts
from data.polymarket_client import PolymarketClient
from strategies.macd_strategy import MACDStrategy
from strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from strategies.cvd_strategy import CVDStrategy
from bot.trader import Trader
from incubation.scaler import Scaler


def main() -> None:
    settings = Settings()
    accounts = load_accounts(settings)
    poly_client = PolymarketClient(accounts[0].client)

    # List of Polymarket token IDs to trade
    # Replace with real token IDs from https://polymarket.com
    watched_markets: list[str] = []

    if not watched_markets:
        print("[Warning] No markets configured in watched_markets. Add token IDs to deploy/run_bot.py")
        return

    scaler = Scaler(seed_size=2.0, full_size=settings.max_position_usdc * 0.1, ramp_days=14)

    trader = Trader(
        settings=settings,
        client=poly_client,
        watched_markets=watched_markets,
        scaler=scaler,
    )
    trader.register_strategy(MACDStrategy())
    trader.register_strategy(RSIMeanReversionStrategy())
    trader.register_strategy(CVDStrategy())

    trader.run()


if __name__ == "__main__":
    main()
