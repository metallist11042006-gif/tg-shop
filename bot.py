"""
DRIP STORE — Telegram Bot Backend
Деплой: Render.com (бесплатный план)
Язык: Python 3.11+
"""

import os
import json
import logging
from telegram import Update, Bot
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# ════════════════════════════════════════════════
# КОНФИГУРАЦИЯ — заполни эти переменные!
# ════════════════════════════════════════════════

# Токен бота (получи у @BotFather)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "СЮДА_ВСТАВЬ_ТОКЕН_БОТА")

# Твой Telegram user ID (получи у @userinfobot)
ADMIN_ID = int(os.environ.get("ADMIN_ID", "СЮДА_ВСТАВЬ_ТВОЙ_ID"))

# Порт для Render
PORT = int(os.environ.get("PORT", 8080))

# ════════════════════════════════════════════════
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CURRENCY_SYMBOLS = {"USD": "$", "UAH": "₴", "PLN": "zł"}
RATES = {"USD": 1, "UAH": 41.5, "PLN": 4.1}


async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ловим данные от Mini App и пересылаем админу."""
    message = update.effective_message
    user = update.effective_user

    if not message or not message.web_app_data:
        return

    raw = message.web_app_data.data
    logger.info(f"Получен заказ от {user.id}: {raw}")

    try:
        order = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Не удалось распарсить JSON заказа")
        await message.reply_text("❌ Ошибка при оформлении заказа. Попробуй ещё раз.")
        return

    # ─── Формируем сообщение для покупателя ──────
    buyer_text = (
        "✅ <b>Заказ принят!</b>\n\n"
        "Наш менеджер свяжется с тобой в ближайшее время для подтверждения и оплаты.\n\n"
        "🛒 <b>Твой заказ:</b>\n"
        + format_items_for_buyer(order)
        + f"\n💰 <b>Итого:</b> {order.get('total_display', '—')}"
    )
    await message.reply_text(buyer_text, parse_mode=ParseMode.HTML)

    # ─── Формируем сообщение для АДМИНА ──────────
    username = user.username
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    
    if username:
        user_link = f'<a href="tg://user?id={user.id}">@{username}</a>'
        contact_hint = f"Написать: @{username}"
    else:
        user_link = f'<a href="tg://user?id={user.id}">{full_name}</a>'
        contact_hint = f"ID: {user.id} (нет username, напиши в ответ)"

    admin_text = (
        f"🔔 <b>НОВЫЙ ЗАКАЗ!</b>\n\n"
        f"👤 Покупатель: {user_link}\n"
        f"📛 Имя: {full_name}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"📲 {contact_hint}\n\n"
        f"🛒 <b>Состав заказа:</b>\n"
        + format_items_for_admin(order)
        + f"\n💵 Валюта покупателя: {order.get('currency', 'USD')}\n"
        f"💰 <b>ИТОГО: {order.get('total_display', '—')}</b>\n"
        f"   (≈ ${order.get('total_usd', '0')} USD)\n\n"
        f"⚡️ Напиши покупателю для оплаты!"
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_text,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение админу: {e}")


def format_items_for_buyer(order):
    items = order.get("items", [])
    cur = order.get("currency", "USD")
    sym = CURRENCY_SYMBOLS.get(cur, "$")
    rate = RATES.get(cur, 1)
    lines = []
    for i, item in enumerate(items, 1):
        price = item.get("price_usd", 0) * rate
        size_str = f" | Размер: {item['size']}" if item.get("size") else ""
        qty = item.get("qty", 1)
        price_str = f"{price * qty:.0f} {sym}" if cur != "USD" else f"${price * qty:.0f}"
        lines.append(f"{i}. {item.get('brand','')} {item.get('title','')}{size_str} × {qty} — {price_str}")
    return "\n".join(lines)


def format_items_for_admin(order):
    items = order.get("items", [])
    cur = order.get("currency", "USD")
    sym = CURRENCY_SYMBOLS.get(cur, "$")
    rate = RATES.get(cur, 1)
    lines = []
    for i, item in enumerate(items, 1):
        price_usd = item.get("price_usd", 0)
        price_conv = price_usd * rate
        size_str = f"  📐 Размер: <b>{item['size']}</b>" if item.get("size") else ""
        qty = item.get("qty", 1)
        lines.append(
            f"{i}. <b>{item.get('brand','')} — {item.get('title','')}</b>\n"
            f"   🔢 Кол-во: {qty}{size_str}\n"
            f"   💵 Цена: ${price_usd:.2f} × {qty} = <b>${price_usd*qty:.2f}</b>"
        )
    return "\n\n".join(lines)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))

    # Для Render — Webhook режим (рекомендуется)
    webhook_url = os.environ.get("WEBHOOK_URL", "")
    if webhook_url:
        logger.info(f"Запуск через Webhook: {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"{webhook_url}/webhook",
            url_path="/webhook"
        )
    else:
        # Для локального тестирования — polling
        logger.info("Запуск через polling (локальный режим)")
        app.run_polling()


if __name__ == "__main__":
    main()
