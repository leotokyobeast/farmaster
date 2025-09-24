import os
from dataclasses import dataclass
from dotenv import load_dotenv


load_dotenv()


@dataclass
class Settings:
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    aster_api_base_url: str = os.getenv("ASTER_API_BASE_URL", "https://fapi.asterdex.com")
    aster_api_key: str = os.getenv("ASTER_API_KEY", "")
    aster_api_secret: str = os.getenv("ASTER_API_SECRET", "")
    default_symbol: str = os.getenv("DEFAULT_SYMBOL", "BTCUSDT")
    aster_timeout_seconds: float = float(os.getenv("ASTER_TIMEOUT_SECONDS", "5"))
    aster_retries: int = int(os.getenv("ASTER_RETRIES", "1"))

    # EVM connector
    evm_user: str = os.getenv("ASTER_EVM_USER", "")
    evm_signer: str = os.getenv("ASTER_EVM_SIGNER", "")
    evm_private_key: str = os.getenv("ASTER_EVM_PRIVATE_KEY", "")


settings = Settings()
