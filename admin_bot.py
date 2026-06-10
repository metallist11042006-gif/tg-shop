"""
NOVA SHOP — Admin Bot
Бот для добавления товаров через Telegram
"""

import os
import json
import logging
import asyncio
import httpx
from aiohttp import web
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════
# КОНФИГ — заполни все три переменные
# ══════════════════════════════════════
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "СЮДА_ТОКЕН_АДМИН_БОТА")
ADMIN_ID        = int(os.environ.get("ADMIN_ID", "СЮДА_ТВОЙ_ID"))
JSONBIN_KEY     = os.environ.get("JSONBIN_KEY", "СЮДА_MASTER_KEY")
JSONBIN_BIN_ID  = os.environ.get("JSONBIN_BIN_ID", "СЮДА_BIN_ID")

PORT        = int(os.environ.get("PORT", 8080))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

JSONBIN_URL = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
HEADERS = {
    "X-Master-Key": JSONBIN_KEY,
    "Content-Type": "application/json"
}

# Шаги диалога
PHOTO, CATEGORY, BRAND, TITLE, PRICE, SIZES, DESCRIPTION = range(7)

CATEGORIES = ["Кроссовки", "Одежда", "Сумки", "Аксессуары"]

# ══════════════════════════════════════
# JSONBIN HELPERS
# ══════════════════════════════════════
async def get_products():
    async with httpx.AsyncClient() as client:
        r = await client.get(JSONBIN_URL, headers=HEADERS)
        data = r.json()
        return data.get("record", {}).get("products", [])

async def save_products(products):
    async with httpx.AsyncClient() as client:
        await client.put(
            JSONBIN_URL,
            headers=HEADERS,
            json={"products": products}
        )

# ══════════════════════════════════════
# КОМАНДЫ
# ══════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ Нет доступа.")
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 Привет! Я помогу добавить товар в магазин.\n\n"
        "Команды:\n"
        "/add — добавить товар\n"
        "/list — список товаров\n"
        "/delete — удалить товар\n"
        "/cancel — отменить"
    )

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    products = await get_products()
    if not products:
        await update.message.reply_text("📦 Товаров пока нет.")
        return
    text = f"📦 Товаров в базе: {len(products)}\n\n"
    for p in products[-10:]:  # последние 10
        text += f"#{p['id']} {p['Brand']} — {p['Title']} | ${p['Price_USD']} | {p['Category']}\n"
    if len(products) > 10:
        text += f"\n...и ещё {len(products)-10} товаров"
    await update.message.reply_text(text)

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text(
        "Напиши ID товара который хочешь удалить.\n"
        "Посмотри ID командой /list"
    )

async def handle_delete_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = update.message.text.strip()
    if not text.startswith("del:"):
        return
    del_id = text.replace("del:", "").strip()
    products = await get_products()
    new_products = [p for p in products if str(p['id']) != str(del_id)]
    if len(new_products) == len(products):
        await update.message.reply_text(f"❌ Товар #{del_id} не найден.")
        return
    await save_products(new_products)
    await update.message.reply_text(f"✅ Товар #{del_id} удалён!")

# ══════════════════════════════════════
# ДОБАВЛЕНИЕ ТОВАРА — диалог
# ══════════════════════════════════════
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ Нет доступа.")
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text(
        "📸 Отправь фото товара\n"
        "(или напиши /skip если фото нет)",
        reply_markup=ReplyKeyboardRemove()
    )
    return PHOTO

async def got_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Загружаю фото...")
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        # Скачиваем фото из Telegram
        async with httpx.AsyncClient() as client:
            tg_url = f"https://api.telegram.org/file/bot{ADMIN_BOT_TOKEN}/{file.file_path}"
            img_resp = await client.get(tg_url)
            img_data = img_resp.content
            # Загружаем на imgur (анонимно, без API key)
            imgur_resp = await client.post(
                "https://api.imgur.com/3/image",
                headers={"Authorization": "Client-ID 546c25a59c58ad7"},
                data={"image": img_data.hex(), "type": "file"},
                files={"image": ("photo.jpg", img_data, "image/jpeg")}
            )
            imgur_data = imgur_resp.json()
            if imgur_data.get("success"):
                context.user_data['image'] = imgur_data["data"]["link"]
                await update.message.reply_text("✅ Фото загружено!")
            else:
                context.user_data['image'] = f"https://api.telegram.org/file/bot{ADMIN_BOT_TOKEN}/{file.file_path}"
    except Exception as e:
        logger.error(f"Photo upload error: {e}")
        context.user_data['image'] = ''
        await update.message.reply_text("⚠️ Не удалось загрузить фото, продолжаем без него")
    return await ask_category(update, context)

async def skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['image'] = ''
    return await ask_category(update, context)

async def ask_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[cat] for cat in CATEGORIES]
    await update.message.reply_text(
        "📂 Выбери категорию:",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True)
    )
    return CATEGORY

async def got_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = update.message.text.strip()
    if cat not in CATEGORIES:
        await update.message.reply_text("❌ Выбери из списка!")
        return CATEGORY
    context.user_data['category'] = cat

    # Популярные бренды по категории
    brands = {
        "Кроссовки": ["Nike", "Adidas", "Jordan", "New Balance", "Balenciaga", "Dior", "Gucci", "Другой"],
        "Одежда":    ["Supreme", "Stone Island", "Moncler", "Trapstar", "Miu Miu", "Acne Studios", "Chrome Hearts", "Другой"],
        "Сумки":     ["Louis Vuitton", "Gucci", "Prada", "Chanel", "Dior", "Balenciaga", "Другой"],
        "Аксессуары":["Rolex", "Cartier", "Chrome Hearts", "Gucci", "Ray-Ban", "Другой"],
    }
    kb = [[b] for b in brands.get(cat, ["Другой"])]
    await update.message.reply_text(
        "👟 Выбери бренд или нажми 'Другой' и напиши сам:",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True)
    )
    return BRAND

async def got_brand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    brand = update.message.text.strip()
    if brand == "Другой":
        await update.message.reply_text("✏️ Напиши название бренда:", reply_markup=ReplyKeyboardRemove())
        return BRAND
    context.user_data['brand'] = brand
    await update.message.reply_text("✏️ Название товара:", reply_markup=ReplyKeyboardRemove())
    return TITLE

async def got_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Если бренд ещё не выбран (написали сами)
    if 'brand' not in context.user_data:
        context.user_data['brand'] = update.message.text.strip()
        await update.message.reply_text("✏️ Название товара:")
        return TITLE
    context.user_data['title'] = update.message.text.strip()
    await update.message.reply_text("💵 Цена в долларах (только число, например: 150):")
    return PRICE

async def got_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Если title ещё не задан
    if 'title' not in context.user_data:
        context.user_data['title'] = update.message.text.strip()
        await update.message.reply_text("💵 Цена в долларах (только число):")
        return PRICE
    try:
        price = float(update.message.text.strip().replace(',', '.'))
        context.user_data['price'] = price
    except:
        await update.message.reply_text("❌ Введи только число, например: 150")
        return PRICE
    await update.message.reply_text(
        "📐 Размеры через запятую без пробелов:\n"
        "Для обуви: 39,40,41,42,43,44\n"
        "Для одежды: S,M,L,XL,XXL\n"
        "Если размеров нет — напиши /skip"
    )
    return SIZES

async def got_sizes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sizes'] = update.message.text.strip()
    await update.message.reply_text("📝 Описание товара (или /skip):")
    return DESCRIPTION

async def skip_sizes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sizes'] = ''
    await update.message.reply_text("📝 Описание товара (или /skip):")
    return DESCRIPTION

async def got_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['description'] = update.message.text.strip()
    return await save_product(update, context)

async def skip_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['description'] = ''
    return await save_product(update, context)

async def save_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = await get_products()
    new_id = str(len(products) + 1) if not products else str(int(products[-1]['id']) + 1)

    product = {
        "id": new_id,
        "Category": context.user_data.get('category', ''),
        "Brand": context.user_data.get('brand', ''),
        "Title": context.user_data.get('title', ''),
        "Price_USD": context.user_data.get('price', 0),
        "Sizes": context.user_data.get('sizes', ''),
        "Image": context.user_data.get('image', ''),
        "Description": context.user_data.get('description', '')
    }

    products.append(product)
    await save_products(products)

    await update.message.reply_text(
        f"✅ Товар добавлен!\n\n"
        f"#{new_id} {product['Brand']} — {product['Title']}\n"
        f"Категория: {product['Category']}\n"
        f"Цена: ${product['Price_USD']}\n"
        f"Размеры: {product['Sizes'] or '—'}\n\n"
        f"Добавить ещё? /add\n"
        f"Список товаров: /list",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ══════════════════════════════════════
# ЗАПУСК
# ══════════════════════════════════════
async def main():
    app = Application.builder().token(ADMIN_BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("add", cmd_add)],
        states={
            PHOTO:       [MessageHandler(filters.PHOTO, got_photo),
                          CommandHandler("skip", skip_photo)],
            CATEGORY:    [MessageHandler(filters.TEXT & ~filters.COMMAND, got_category)],
            BRAND:       [MessageHandler(filters.TEXT & ~filters.COMMAND, got_brand)],
            TITLE:       [MessageHandler(filters.TEXT & ~filters.COMMAND, got_title)],
            PRICE:       [MessageHandler(filters.TEXT & ~filters.COMMAND, got_price)],
            SIZES:       [MessageHandler(filters.TEXT & ~filters.COMMAND, got_sizes),
                          CommandHandler("skip", skip_sizes)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_description),
                          CommandHandler("skip", skip_description)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^del:'), handle_delete_id))
    app.add_handler(conv)

    if WEBHOOK_URL:
        webhook_path = "/webhook"
        await app.initialize()
        await app.bot.set_webhook(url=f"{WEBHOOK_URL}{webhook_path}")
        await app.start()

        async def tg_webhook(request):
            data = await request.json()
            update = Update.de_json(data, app.bot)
            await app.process_update(update)
            return web.Response(text="OK")

        web_app = web.Application()
        web_app.router.add_post(webhook_path, tg_webhook)
        web_app.router.add_get("/", lambda r: web.Response(text="OK"))
        runner = web.AppRunner(web_app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", PORT).start()
        logger.info(f"Admin bot running on port {PORT}")
        while True:
            await asyncio.sleep(3600)
    else:
        await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
