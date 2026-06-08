import os
import json
import logging
import asyncio
from aiohttp import web
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from telegram.constants import ParseMode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
PORT = int(os.environ.get("PORT", 8080))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

CURRENCY_SYMBOLS = {"USD": "$", "UAH": "₴", "PLN": "zł"}
RATES = {"USD": 1, "UAH": 41.5, "PLN": 4.1}


async def cmd_start(update, context):
    await update.message.reply_text(
        "👋 Привет! Нажми кнопку *Открыть магазин* внизу слева 👇",
        parse_mode=ParseMode.MARKDOWN
    )


async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    if not message or not message.web_app_data:
        return

    raw = message.web_app_data.data
    logger.info(f"Заказ от {user.id}: {raw}")

    try:
        order = json.loads(raw)
    except json.JSONDecodeError:
        await message.reply_text("❌ Ошибка заказа. Попробуй ещё раз.")
        return

    buyer_text = (
        "✅ <b>Заказ принят!</b>\n\n"
        "Менеджер свяжется с тобой в ближайшее время для подтверждения и оплаты.\n\n"
        "🛒 <b>Твой заказ:</b>\n"
        + format_items(order, for_admin=False)
        + f"\n\n💰 <b>Итого:</b> {order.get('total_display', '—')}"
    )
    await message.reply_text(buyer_text, parse_mode=ParseMode.HTML)

    username = user.username
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    if username:
        user_link = f'<a href="tg://user?id={user.id}">@{username}</a>'
        contact = f"@{username}"
    else:
        user_link = f'<a href="tg://user?id={user.id}">{full_name}</a>'
        contact = f"ID: {user.id} (нет username)"

    admin_text = (
        f"🔔 <b>НОВЫЙ ЗАКАЗ!</b>\n\n"
        f"👤 {user_link}\n"
        f"📛 {full_name}\n"
        f"📲 {contact}\n\n"
        f"🛒 <b>Состав:</b>\n"
        + format_items(order, for_admin=True)
        + f"\n\n💵 Валюта: {order.get('currency', 'USD')}\n"
        f"💰 <b>ИТОГО: {order.get('total_display', '—')}</b> (≈ ${order.get('total_usd', '0')} USD)\n\n"
        f"⚡️ Напиши покупателю!"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка отправки админу: {e}")


def format_items(order, for_admin=False):
    items = order.get("items", [])
    cur = order.get("currency", "USD")
    sym = CURRENCY_SYMBOLS.get(cur, "$")
    rate = RATES.get(cur, 1)
    lines = []
    for i, item in enumerate(items, 1):
        p = item.get("price_usd", 0)
        qty = item.get("qty", 1)
        size = f" | р.{item['size']}" if item.get("size") else ""
        total = p * qty * rate
        price_str = f"${p * qty:.0f}" if cur == "USD" else f"{total:.0f} {sym}"
        name = f"{item.get('brand', '')} {item.get('title', '')}"
        if for_admin:
            lines.append(f"{i}. <b>{name}</b>{size} × {qty} — {price_str}")
        else:
            lines.append(f"{i}. {name}{size} × {qty} — {price_str}")
    return "\n".join(lines)


async def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))

    if WEBHOOK_URL:
        webhook_path = "/webhook"
        full_url = f"{WEBHOOK_URL}{webhook_path}"
        logger.info(f"Webhook mode: {full_url}")

        await application.initialize()
        await application.bot.set_webhook(url=full_url)
        await application.start()

        async def telegram_webhook(request):
            data = await request.json()
            update = Update.de_json(data, application.bot)
            await application.process_update(update)
            return web.Response(text="OK")

        async def health(request):
            return web.Response(text="OK")

        web_app = web.Application()
        web_app.router.add_post(webhook_path, telegram_webhook)
        web_app.router.add_get("/", health)

        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", PORT)
        await site.start()
        logger.info(f"Server on port {PORT}")

        while True:
            await asyncio.sleep(3600)
    else:
        logger.info("Polling mode")
        await application.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
