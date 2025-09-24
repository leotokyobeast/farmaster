import logging
from typing import Optional, List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, Defaults
from telegram.constants import ParseMode

from config import settings
from aster.aclient import AsterAsyncClient
from aster.evm_client import AsterEvmClient


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("farmaster")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:  # noqa: BLE001
        return default


def get_client() -> AsterAsyncClient:
    return AsterAsyncClient(
        base_url=settings.aster_api_base_url,
        api_key=settings.aster_api_key,
        api_secret=settings.aster_api_secret,
        timeout_seconds=settings.aster_timeout_seconds,
        retries=settings.aster_retries,
    )


def get_evm_client() -> AsterEvmClient:
    return AsterEvmClient(
        base_url=settings.aster_api_base_url,
        user=settings.evm_user,
        signer=settings.evm_signer,
        private_key=settings.evm_private_key,
        timeout_seconds=max(5.0, settings.aster_timeout_seconds),
    )


def main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Your Positions", callback_data="positions")],
        [InlineKeyboardButton("Buy Order (open)", callback_data="buy"), InlineKeyboardButton("Sell Order (close)", callback_data="sell")],
        [InlineKeyboardButton("Change Leverage", callback_data="leverage"), InlineKeyboardButton("Edit Margin", callback_data="margin")],
        [InlineKeyboardButton("EVM Order", callback_data="getorder")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = get_client()
    # Prices list, one per row with 24h change FIRST, then arrow, then $price
    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ASTERUSDT"]
    price_lines: List[str] = []
    try:
        for s in symbols:
            try:
                p = await client.get_symbol_price(s)
                chg = await client.get_24h_change_percent(s)
                arrow = "▲" if chg >= 0 else "▼"
                price_lines.append(f"• <b>{s[:-4]}</b>  <b>{chg:+.2f}%</b> {arrow} <b>${p:,.2f}</b>")
            except Exception:  # noqa: BLE001
                price_lines.append(f"• <b>{s[:-4]}</b>  —")
    except Exception as e:
        logger.warning("prices fetch failed: %s", e)

    # Account
    try:
        account = await client.get_account_v4()
    except Exception as e:
        logger.warning("/start account fetch failed: %s", e)
        await update.effective_chat.send_message(
            "Welcome to FarmAster for ASTER DEX perps! Let's farm https://www.asterdex.com \n\n"
            + ("\n".join(price_lines) if price_lines else "") +
            "\n\nUnable to fetch account right now. Try again later.",
            reply_markup=main_menu(),
            parse_mode=ParseMode.HTML,
        )
        await client.aclose()
        return

    positions: List[Dict[str, Any]] = []
    if isinstance(account, dict):
        positions = account.get("positions", []) or []

    # Totals
    total_margin_balance = safe_float(account.get("totalMarginBalance") if isinstance(account, dict) else 0)
    available_balance = safe_float(account.get("availableBalance") if isinstance(account, dict) else 0)
    total_pos_im = safe_float(account.get("totalPositionInitialMargin") if isinstance(account, dict) else 0)
    total_open_im = safe_float(account.get("totalOpenOrderInitialMargin") if isinstance(account, dict) else 0)
    margin_used = total_pos_im + total_open_im

    # Build mark price and OI maps
    nonzero = [p for p in positions if safe_float(p.get("positionAmt")) != 0.0]
    unique_syms = sorted({p.get("symbol", "") for p in nonzero if p.get("symbol")})
    mark_map: Dict[str, float] = {}
    oi_map: Dict[str, float] = {}
    for sym in unique_syms:
        try:
            mark_map[sym] = await client.get_mark_price(sym)
        except Exception:  # noqa: BLE001
            mark_map[sym] = 0.0
        try:
            oi_map[sym] = await client.get_open_interest(sym)
        except Exception:  # noqa: BLE001
            oi_map[sym] = 0.0

    # Compute total unrealized pnl across positions (mark-based)
    total_unrealized = 0.0
    for p in nonzero:
        amt = safe_float(p.get("positionAmt"))
        entry = safe_float(p.get("entryPrice"))
        mark = mark_map.get(p.get("symbol", ""), 0.0)
        total_unrealized += (mark - entry) * amt

    # Position lines — append open interest to line2
    lines: List[str] = []
    for p in nonzero:
        sym = p.get("symbol", "?")
        amt = safe_float(p.get("positionAmt"))
        lev = safe_float(p.get("leverage"))
        entry = safe_float(p.get("entryPrice"))
        mark = mark_map.get(sym, 0.0)
        oi = oi_map.get(sym, 0.0)

        pnl = (mark - entry) * amt
        cost_basis = abs(amt) * entry if entry > 0 else 0.0
        ret_pct = (pnl / cost_basis * 100.0) if cost_basis > 0 else 0.0

        header = f"• <b>{sym[:-4]}/USDT</b> x{lev:g}"
        line2 = f"<b>${pnl:,.2f}</b> PNL | <b>{ret_pct:,.2f}%</b> return | open interest <b>{oi:,.0f}</b>"
        lines.append(header)
        lines.append(line2)
        lines.append("")

    summary_header = (
        "Welcome to FarmAster for ASTER DEX perps!\n\n"
        + ("\n".join(price_lines) if price_lines else "") + "\n\n"
        + f"Your portfolio: <b>${total_margin_balance:,.2f}</b>\n"
        + f"Unrealized return: <b>${total_unrealized:,.2f}</b>\n"
        + f"Margin used: <b>${margin_used:,.2f}</b>\n"
        + f"Margin available: <b>${available_balance:,.2f}</b>\n\n"
        + "Your positions:\n"
    )

    summary = (summary_header + ("\n".join(lines) if lines else "None")).rstrip()

    await update.effective_chat.send_message(summary, reply_markup=main_menu(), parse_mode=ParseMode.HTML)
    await client.aclose()


async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = get_client()
    try:
        account = await client.get_account_v4()
        positions = account.get("positions", []) if isinstance(account, dict) else []
        nonzero = [p for p in positions if safe_float(p.get("positionAmt")) != 0.0]
        unique_syms = sorted({p.get("symbol", "") for p in nonzero if p.get("symbol")})
        mark_map: Dict[str, float] = {}
        oi_map: Dict[str, float] = {}
        for sym in unique_syms:
            try:
                mark_map[sym] = await client.get_mark_price(sym)
            except Exception:  # noqa: BLE001
                mark_map[sym] = 0.0
            try:
                oi_map[sym] = await client.get_open_interest(sym)
            except Exception:  # noqa: BLE001
                oi_map[sym] = 0.0

        lines: List[str] = []
        for p in nonzero:
            sym = p.get("symbol", "?")
            amt = safe_float(p.get("positionAmt"))
            lev = safe_float(p.get("leverage"))
            entry = safe_float(p.get("entryPrice"))
            mark = mark_map.get(sym, 0.0)
            oi = oi_map.get(sym, 0.0)

            pnl = (mark - entry) * amt
            cost_basis = abs(amt) * entry if entry > 0 else 0.0
            ret_pct = (pnl / cost_basis * 100.0) if cost_basis > 0 else 0.0

            header = f"• <b>{sym[:-4]}/USDT</b> x{lev:g}"
            line2 = f"<b>${pnl:,.2f}</b> PNL | <b>{ret_pct:,.2f}%</b> return | open interest <b>{oi:,.0f}</b>"
            lines.append(header)
            lines.append(line2)
            lines.append("")

        text = ("Your positions:\n" + ("\n".join(lines) if lines else "None")).rstrip()
    except Exception as e:
        logger.exception("positions error")
        text = f"Error fetching positions: {e}"
    finally:
        await client.aclose()
    await update.effective_chat.send_message(text, parse_mode=ParseMode.HTML)


async def evm_get_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 1:
        await update.effective_chat.send_message("Usage: /getorder <SYMBOL> [orderId]")
        return
    symbol = context.args[0]
    order_id = int(context.args[1]) if len(context.args) > 1 else None
    client = get_evm_client()
    try:
        data = await client.get_order(symbol=symbol, order_id=order_id, side=None, order_type=None)
        text = f"EVM getOrder: {data}"
    except Exception as e:
        logger.exception("evm getorder error")
        text = f"Error: {e}"
    finally:
        await client.aclose()
    await update.effective_chat.send_message(text)


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    symbol = settings.default_symbol
    qty: Optional[float] = None
    if context.args:
        try:
            qty = float(context.args[0])
        except Exception:  # noqa: BLE001
            pass
    if qty is None:
        await update.effective_chat.send_message("Usage: /buy <quantity>")
        return
    client = get_client()
    try:
        data = await client.place_order(symbol=symbol, side="BUY", quantity=qty)
        text = f"Buy order placed: {data}"
    except Exception as e:
        logger.exception("buy error")
        text = f"Error placing buy: {e}"
    finally:
        await client.aclose()
    await update.effective_chat.send_message(text)


async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    symbol = settings.default_symbol
    qty: Optional[float] = None
    if context.args:
        try:
            qty = float(context.args[0])
        except Exception:  # noqa: BLE001
            pass
    if qty is None:
        await update.effective_chat.send_message("Usage: /sell <quantity>")
        return
    client = get_client()
    try:
        data = await client.place_order(symbol=symbol, side="SELL", quantity=qty)
        text = f"Sell order placed: {data}"
    except Exception as e:
        logger.exception("sell error")
        text = f"Error placing sell: {e}"
    finally:
        await client.aclose()
    await update.effective_chat.send_message(text)


async def leverage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    symbol = settings.default_symbol
    lev: Optional[int] = None
    if context.args:
        try:
            lev = int(context.args[0])
        except Exception:  # noqa: BLE001
            pass
    if lev is None:
        await update.effective_chat.send_message("Usage: /leverage <integer>")
        return
    client = get_client()
    try:
        data = await client.set_leverage(symbol=symbol, leverage=lev)
        text = f"Leverage updated: {data}"
    except Exception as e:
        logger.exception("leverage error")
        text = f"Error setting leverage: {e}"
    finally:
        await client.aclose()
    await update.effective_chat.send_message(text)


async def margin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    symbol = settings.default_symbol
    amount: Optional[float] = None
    if context.args:
        try:
            amount = float(context.args[0])
        except Exception:  # noqa: BLE001
            pass
    if amount is None:
        await update.effective_chat.send_message("Usage: /margin <amount>")
        return
    client = get_client()
    try:
        data = await client.adjust_margin(symbol=symbol, amount=amount)
        text = f"Margin adjusted: {data}"
    except Exception as e:
        logger.exception("margin error")
        text = f"Error adjusting margin: {e}"
    finally:
        await client.aclose()
    await update.effective_chat.send_message(text)


def build_app() -> Application:
    defaults = Defaults(parse_mode=ParseMode.HTML)
    app = Application.builder().token(settings.telegram_bot_token).concurrent_updates(True).defaults(defaults).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("positions", positions))
    app.add_handler(CommandHandler("getorder", evm_get_order))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("sell", sell))
    app.add_handler(CommandHandler("leverage", leverage))
    app.add_handler(CommandHandler("margin", margin))
    return app


if __name__ == "__main__":
    application = build_app()
    logger.info("Starting FarmAster bot")
    application.run_polling()
