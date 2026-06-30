from dataclasses import dataclass

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

from config.settings import Settings


@dataclass
class AccountConfig:
    label: str
    client: ClobClient
    settings: Settings


def load_accounts(settings: Settings) -> list[AccountConfig]:
    """Return a list of configured Polymarket accounts.

    Currently supports a single account. Structured as a list for future
    multi-wallet expansion without API changes.
    """
    creds = ApiCreds(
        api_key=settings.poly_api_key,
        api_secret=settings.poly_api_secret,
        api_passphrase=settings.poly_api_passphrase,
    )
    client = ClobClient(
        host=settings.poly_host,
        key=settings.poly_private_key,
        chain_id=137,  # Polygon mainnet
        creds=creds,
    )
    return [AccountConfig(label="main", client=client, settings=settings)]
