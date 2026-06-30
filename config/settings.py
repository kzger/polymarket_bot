from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Polymarket CLOB credentials
    poly_private_key: str = ""
    poly_api_key: str = ""
    poly_api_secret: str = ""
    poly_api_passphrase: str = ""
    poly_host: str = "https://clob.polymarket.com"

    # Binance data feed
    binance_symbol: str = "ETH/USDT"
    candle_interval: str = "5m"

    # Bot execution
    poll_interval_seconds: int = 300

    # Risk controls
    max_position_usdc: float = 500.0
    max_daily_loss_usdc: float = 100.0
    max_open_orders: int = 10
    min_order_size_usdc: float = 1.0

    # Storage
    storage_backend: str = "csv"  # "csv" | "sqlite"
