# FarmAster Telegram Trading Bot (ASTER DEX)

A Telegram bot to trade on ASTER DEX futures: view positions, place buy/sell orders, change leverage and margin.

## Quick Start (Windows PowerShell)

1. Install Python 3.10+
2. Create and activate a virtual environment
3. Install dependencies
4. Copy `.env.example` to `.env` and fill values
5. Run the bot

```powershell
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m bot.main
```

## Environment Variables

- TELEGRAM_BOT_TOKEN: Telegram BotFather token
- ASTER_API_BASE_URL: e.g. https://fapi.asterdex.com
- ASTER_EVM_USER: your EVM account address
- ASTER_EVM_SIGNER: signer address used by ASTER
- ASTER_EVM_PRIVATE_KEY: signer private key (0x...)
- DEFAULT_SYMBOL: e.g. BTCUSDT
- ASTER_TIMEOUT_SECONDS, ASTER_RETRIES: networking tuning

Docs: [`aster-finance-futures-api.md`](https://github.com/asterdex/api-docs/blob/master/aster-finance-futures-api.md)

## Project Layout

- `bot/` Telegram handlers and entrypoint
- `aster/` ASTER API clients (HTTP and EVM)
- `config.py` settings loader

## Disclaimer

For educational purposes. Trade responsibly.
