"""
NOVA SHOP — Admin Bot
Полное управление товарами
"""

import os
import json
import logging
import asyncio
import base64
import httpx
from aiohttp import web
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════
# КОНФИГ
# ══════════════════════════════════════
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "")
ADMIN_ID        = int(os.environ.get("ADMIN_ID", "0"))
JSONBIN_KEY     = os.environ.get("JSONBIN_KEY", "")
JSONBIN_BIN_ID  = os.environ.get("JSONBIN_BIN_ID", "")
IMGBB_KEY       = os.environ.get("IMGBB_KEY", "")
PORT            = int(os.environ.get("PORT", 8080))
WEBHOOK_URL     = os.environ.get("WEBHOOK_URL", "")

JSONBIN_URL = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
HEADERS = {"X-Master-Key": JSONBIN_KEY, "Content-Type": "application/json"}

CATEGORIES = ["Кроссовки", "Одежда", "Сумки", "Аксессуары"]

# Шаги добавления
PHOTO, MORE_PHOTOS, CATEGORY, BRAND, TITLE, PRICE, SIZES, DESCRIPTION = range(8)
# Шаги редактирования
EDIT_CHOOSE, EDIT_FIELD, EDIT_VALUE, EDIT_PHOTO = range(10, 14)

# ══════════════════════════════════════
# JSONBIN
# ══════════════════════════════════════
async def get_products():
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{JSONBIN_URL}/latest", headers=HEADERS)
        data = r.json()
        return data.get("record", {}).get("products", [])

async def save_products(products):
    async with httpx.AsyncClient(timeout=15) as client:
        await client.put(JSONBIN_URL, headers=HEADERS, json={"products": products})

# ══════════════════════════════════════
# IMGBB
# ══════════════════════════════════════
async def upload_photo(bot, file_id):
    file = await bot.get_file(file_id)
    async with httpx.AsyncClient(timeout=60) as client:
        # file.file_path может быть полным URL или относительным путём
        fp = file.file_path
        if fp.startswith("http"):
            tg_url = fp
        else:
            tg_url = f"https://api.telegram.org/file/bot{ADMIN_BOT_TOKEN}/{fp}"
        logger.info(f"Downloading photo from: {tg_url}")
        img_resp = await client.get(tg_url)
        logger.info(f"Download status: {img_resp.status_code}, size: {len(img_resp.content)}")
        if img_resp.status_code != 200:
            logger.error(f"Failed to download photo: {img_resp.status_code}")
            return None
        img_bytes = img_resp.content
        b64 = base64.b64encode(img_bytes).decode('utf-8')
        resp = await client.post(
            "https://api.imgbb.com/1/upload",
            params={"key": IMGBB_KEY},
            data={"image": b64}
        )
        logger.info(f"ImgBB response: {resp.status_code} {resp.text[:300]}")
        data = resp.json()
        if data.get("success"):
            return data["data"]["display_url"]
        logger.error(f"ImgBB failed: {data}")
        return None

# ══════════════════════════════════════
# GUARD
# ══════════════════════════════════════
def is_admin(update):
    return update.effective_user.id == ADMIN_ID

# ══════════════════════════════════════
# /start — главное меню
# ══════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    kb = [["➕ Добавить товар", "📦 Список товаров"],
          ["✏️ Редактировать", "🗑 Удалить товар"],
          ["🚫 Распродано / Скрыть", "✅ Восстановить товар"]]
    await update.message.reply_text(
        "👋 NOVA SHOP Admin\nВыбери действие:",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

# ══════════════════════════════════════
# СПИСОК ТОВАРОВ
# ══════════════════════════════════════
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    products = await get_products()
    if not products:
        await update.message.reply_text("📦 Товаров пока нет.")
        return
    # Группируем по категории
    cats = {}
    for p in products:
        cat = p.get('Category', '—')
        cats.setdefault(cat, []).append(p)
    text = f"📦 Всего товаров: {len(products)}\n"
    for cat, items in cats.items():
        text += f"\n━━ {cat} ({len(items)}) ━━\n"
        for p in items:
            status = " 🚫" if p.get('sold_out') else (" 👁" if p.get('hidden') else "")
            text += f"#{p['id']} {p['Brand']} — {p['Title']} | ${p['Price_USD']}{status}\n"
    await update.message.reply_text(text)

# ══════════════════════════════════════
# ДОБАВИТЬ ТОВАР
# ══════════════════════════════════════
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text(
        "📸 Отправь фото товара\n(или /skip если нет фото)",
        reply_markup=ReplyKeyboardRemove()
    )
    return PHOTO

async def got_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Загружаю фото...")
    url = await upload_photo(context.bot, update.message.photo[-1].file_id)
    if url:
        if not context.user_data.get('images'):
            context.user_data['images'] = []
        context.user_data['images'].append(url)
        count = len(context.user_data['images'])
        kb = ReplyKeyboardMarkup([["➡️ Продолжить"]], resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            f"✅ Фото {count} загружено!

"
            f"Отправь ещё фото (до 6 штук)
или нажми ➡️ Продолжить",
            reply_markup=kb
        )
        return MORE_PHOTOS
    else:
        context.user_data['images'] = []
        await update.message.reply_text("⚠️ Фото не загрузилось, продолжаем без него")
        return await ask_category(update, context)

async def more_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "➡️ Продолжить":
        return await ask_category(update, context)
    await update.message.reply_text("Отправь фото или нажми ➡️ Продолжить")
    return MORE_PHOTOS

async def more_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    images = context.user_data.get('images', [])
    if len(images) >= 6:
        await update.message.reply_text("Максимум 6 фото. Нажми ➡️ Продолжить")
        return MORE_PHOTOS
    await update.message.reply_text("⏳ Загружаю фото...")
    url = await upload_photo(context.bot, update.message.photo[-1].file_id)
    if url:
        images.append(url)
        context.user_data['images'] = images
        count = len(images)
        kb = ReplyKeyboardMarkup([["➡️ Продолжить"]], resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            f"✅ Фото {count} загружено!

"
            f"Отправь ещё или нажми ➡️ Продолжить",
            reply_markup=kb
        )
    else:
        await update.message.reply_text("⚠️ Не загрузилось, попробуй ещё раз")
    return MORE_PHOTOS

async def skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['images'] = []
    return await ask_category(update, context)

async def ask_category(update, context):
    kb = [[c] for c in CATEGORIES]
    await update.message.reply_text(
        "📂 Категория:",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True)
    )
    return CATEGORY

async def got_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = update.message.text.strip()
    if cat not in CATEGORIES:
        await update.message.reply_text("❌ Выбери из списка!")
        return CATEGORY
    context.user_data['category'] = cat
    brands = {
        "Кроссовки": ["Nike","Adidas","Jordan","New Balance","Balenciaga","Dior","Gucci","Другой"],
        "Одежда":    ["Supreme","Stone Island","Moncler","Miu Miu","Acne Studios","Chrome Hearts","Trapstar","Другой"],
        "Сумки":     ["Louis Vuitton","Gucci","Prada","Chanel","Dior","Balenciaga","Другой"],
        "Аксессуары":["Rolex","Cartier","Chrome Hearts","Gucci","Ray-Ban","Другой"],
    }
    kb = [[b] for b in brands.get(cat, ["Другой"])]
    await update.message.reply_text("👟 Бренд:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True))
    return BRAND

async def got_brand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    brand = update.message.text.strip()
    if brand == "Другой":
        await update.message.reply_text("✏️ Напиши бренд:", reply_markup=ReplyKeyboardRemove())
        context.user_data['waiting_custom_brand'] = True
        return BRAND
    if context.user_data.get('waiting_custom_brand'):
        context.user_data.pop('waiting_custom_brand')
    context.user_data['brand'] = brand
    await update.message.reply_text("✏️ Название товара:", reply_markup=ReplyKeyboardRemove())
    return TITLE

async def got_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'brand' not in context.user_data:
        context.user_data['brand'] = update.message.text.strip()
        await update.message.reply_text("✏️ Название товара:")
        return TITLE
    context.user_data['title'] = update.message.text.strip()
    await update.message.reply_text("💵 Цена в $ (только число):")
    return PRICE

async def got_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'title' not in context.user_data:
        context.user_data['title'] = update.message.text.strip()
        await update.message.reply_text("💵 Цена в $ (только число):")
        return PRICE
    try:
        context.user_data['price'] = float(update.message.text.strip().replace(',','.'))
    except:
        await update.message.reply_text("❌ Только число, например: 150")
        return PRICE
    await update.message.reply_text(
        "📐 Размеры через запятую:\n"
        "Обувь: 40,41,42,43,44\n"
        "Одежда: S,M,L,XL\n"
        "Нет размеров: /skip"
    )
    return SIZES

async def got_sizes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sizes'] = update.message.text.strip()
    await update.message.reply_text("📝 Описание (или /skip):")
    return DESCRIPTION

async def skip_sizes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sizes'] = ''
    await update.message.reply_text("📝 Описание (или /skip):")
    return DESCRIPTION

async def got_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['description'] = update.message.text.strip()
    return await save_new_product(update, context)

async def skip_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['description'] = ''
    return await save_new_product(update, context)

async def save_new_product(update, context):
    products = await get_products()
    new_id = str(int(products[-1]['id']) + 1) if products else '1'
    images = context.user_data.get('images', [])
    product = {
        "id": new_id,
        "Category": context.user_data.get('category',''),
        "Brand": context.user_data.get('brand',''),
        "Title": context.user_data.get('title',''),
        "Price_USD": context.user_data.get('price', 0),
        "Sizes": context.user_data.get('sizes',''),
        "Image": images[0] if images else '',
        "Images": images,
        "Description": context.user_data.get('description',''),
        "sold_out": False,
        "hidden": False
    }
    products.append(product)
    await save_products(products)
    await update.message.reply_text(
        f"✅ Товар #{new_id} добавлен!\n\n"
        f"{product['Brand']} — {product['Title']}\n"
        f"Категория: {product['Category']}\n"
        f"Цена: ${product['Price_USD']}\n"
        f"Размеры: {product['Sizes'] or '—'}\n\n"
        f"/add — ещё товар\n/list — список",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()
    return ConversationHandler.END

# ══════════════════════════════════════
# РЕДАКТИРОВАТЬ ТОВАР
# ══════════════════════════════════════
async def cmd_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return ConversationHandler.END
    products = await get_products()
    if not products:
        await update.message.reply_text("Товаров нет.")
        return ConversationHandler.END
    context.user_data['products'] = products
    text = "✏️ Введи ID товара для редактирования:\n\n"
    for p in products[-20:]:
        status = " 🚫" if p.get('sold_out') else (" 👁" if p.get('hidden') else "")
        text += f"#{p['id']} {p['Brand']} — {p['Title']}{status}\n"
    await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())
    return EDIT_CHOOSE

async def edit_choose_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = update.message.text.strip().replace('#','')
    products = context.user_data.get('products', [])
    product = next((p for p in products if str(p['id']) == pid), None)
    if not product:
        await update.message.reply_text("❌ Товар не найден. Введи правильный ID:")
        return EDIT_CHOOSE
    context.user_data['edit_id'] = pid
    kb = [
        ["📸 Фото", "📂 Категория"],
        ["👟 Бренд", "✏️ Название"],
        ["💵 Цена", "📐 Размеры"],
        ["📝 Описание", "❌ Отмена"]
    ]
    await update.message.reply_text(
        f"Редактируем: {product['Brand']} — {product['Title']}\n\n"
        f"Что изменить?",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )
    return EDIT_FIELD

async def edit_choose_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = update.message.text.strip()
    if field == "❌ Отмена":
        await update.message.reply_text("Отменено.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    field_map = {
        "📸 Фото": "Image",
        "📂 Категория": "Category",
        "👟 Бренд": "Brand",
        "✏️ Название": "Title",
        "💵 Цена": "Price_USD",
        "📐 Размеры": "Sizes",
        "📝 Описание": "Description"
    }
    if field not in field_map:
        await update.message.reply_text("Выбери из кнопок!")
        return EDIT_FIELD

    context.user_data['edit_field'] = field_map[field]

    if field == "📸 Фото":
        await update.message.reply_text("📸 Отправь новое фото:", reply_markup=ReplyKeyboardRemove())
        return EDIT_PHOTO
    elif field == "📂 Категория":
        kb = [[c] for c in CATEGORIES]
        await update.message.reply_text("Выбери категорию:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True))
    elif field == "💵 Цена":
        await update.message.reply_text("Введи новую цену в $:", reply_markup=ReplyKeyboardRemove())
    elif field == "📐 Размеры":
        await update.message.reply_text("Введи размеры через запятую:\n40,41,42 или S,M,L,XL", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text(f"Введи новое значение:", reply_markup=ReplyKeyboardRemove())
    return EDIT_VALUE

async def edit_new_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Загружаю фото...")
    url = await upload_photo(context.bot, update.message.photo[-1].file_id)
    if not url:
        await update.message.reply_text("❌ Не удалось загрузить. Попробуй ещё раз.")
        return EDIT_PHOTO
    await apply_edit(update, context, url)
    return ConversationHandler.END

async def edit_new_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text.strip()
    field = context.user_data.get('edit_field')
    if field == 'Price_USD':
        try:
            value = float(value.replace(',','.'))
        except:
            await update.message.reply_text("❌ Введи число!")
            return EDIT_VALUE
    await apply_edit(update, context, value)
    return ConversationHandler.END

async def apply_edit(update, context, new_value):
    pid = context.user_data.get('edit_id')
    field = context.user_data.get('edit_field')
    products = await get_products()
    for p in products:
        if str(p['id']) == str(pid):
            p[field] = new_value
            break
    await save_products(products)
    await update.message.reply_text(
        f"✅ Товар #{pid} обновлён!\n{field} → {new_value}",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()

# ══════════════════════════════════════
# УДАЛИТЬ ТОВАР
# ══════════════════════════════════════
async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    products = await get_products()
    if not products:
        await update.message.reply_text("Товаров нет.")
        return
    text = "🗑 Введи: del:ID\nНапример: del:5\n\n"
    for p in products[-20:]:
        text += f"#{p['id']} {p['Brand']} — {p['Title']}\n"
    await update.message.reply_text(text)

async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    text = update.message.text.strip()
    if not text.lower().startswith("del:"): return
    pid = text.split(":")[1].strip()
    products = await get_products()
    new_products = [p for p in products if str(p['id']) != pid]
    if len(new_products) == len(products):
        await update.message.reply_text(f"❌ Товар #{pid} не найден.")
        return
    await save_products(new_products)
    await update.message.reply_text(f"✅ Товар #{pid} удалён!")

# ══════════════════════════════════════
# РАСПРОДАНО / СКРЫТЬ
# ══════════════════════════════════════
async def cmd_soldout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    products = await get_products()
    text = "🚫 Пометить как распродано или скрыть:\n\n"
    text += "sold:ID — пометить 'Распродано'\n"
    text += "hide:ID — скрыть товар\n\n"
    for p in products[-20:]:
        status = " 🚫РАСПРОДАНО" if p.get('sold_out') else (" 👁СКРЫТ" if p.get('hidden') else "")
        text += f"#{p['id']} {p['Brand']} — {p['Title']}{status}\n"
    await update.message.reply_text(text)

async def cmd_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    products = await get_products()
    text = "✅ Восстановить товар:\n\nrestore:ID\n\n"
    hidden = [p for p in products if p.get('sold_out') or p.get('hidden')]
    if not hidden:
        await update.message.reply_text("Нет скрытых или распроданных товаров.")
        return
    for p in hidden:
        status = "🚫" if p.get('sold_out') else "👁"
        text += f"{status} #{p['id']} {p['Brand']} — {p['Title']}\n"
    await update.message.reply_text(text)

async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    text = update.message.text.strip().lower()
    if not any(text.startswith(x) for x in ["sold:", "hide:", "restore:"]): return
    action, pid = text.split(":")[0], text.split(":")[1].strip()
    products = await get_products()
    found = False
    for p in products:
        if str(p['id']) == pid:
            found = True
            if action == "sold":
                p['sold_out'] = True
                p['hidden'] = False
                msg = f"🚫 Товар #{pid} помечен как РАСПРОДАНО"
            elif action == "hide":
                p['hidden'] = True
                p['sold_out'] = False
                msg = f"👁 Товар #{pid} скрыт из каталога"
            elif action == "restore":
                p['sold_out'] = False
                p['hidden'] = False
                msg = f"✅ Товар #{pid} восстановлен!"
            break
    if not found:
        await update.message.reply_text(f"❌ Товар #{pid} не найден.")
        return
    await save_products(products)
    await update.message.reply_text(msg)

# ══════════════════════════════════════
# CANCEL
# ══════════════════════════════════════
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# ══════════════════════════════════════
# MENU HANDLER
# ══════════════════════════════════════
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    text = update.message.text
    if text == "➕ Добавить товар":
        await cmd_add(update, context)
    elif text == "📦 Список товаров":
        await cmd_list(update, context)
    elif text == "✏️ Редактировать":
        await cmd_edit(update, context)
    elif text == "🗑 Удалить товар":
        await cmd_delete(update, context)
    elif text == "🚫 Распродано / Скрыть":
        await cmd_soldout(update, context)
    elif text == "✅ Восстановить товар":
        await cmd_restore(update, context)

# ══════════════════════════════════════
# ЗАПУСК
# ══════════════════════════════════════
async def main():
    app = Application.builder().token(ADMIN_BOT_TOKEN).build()

    add_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add", cmd_add),
            MessageHandler(filters.Regex("^➕ Добавить товар$"), cmd_add)
        ],
        states={
            PHOTO:       [MessageHandler(filters.PHOTO, got_photo),
                          CommandHandler("skip", skip_photo)],
            MORE_PHOTOS: [MessageHandler(filters.PHOTO, more_photo_upload),
                          MessageHandler(filters.TEXT & ~filters.COMMAND, more_photos)],
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

    edit_conv = ConversationHandler(
        entry_points=[
            CommandHandler("edit", cmd_edit),
            MessageHandler(filters.Regex("^✏️ Редактировать$"), cmd_edit)
        ],
        states={
            EDIT_CHOOSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_choose_id)],
            EDIT_FIELD:  [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_choose_field)],
            EDIT_VALUE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_new_value)],
            EDIT_PHOTO:  [MessageHandler(filters.PHOTO, edit_new_photo)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CommandHandler("soldout", cmd_soldout))
    app.add_handler(CommandHandler("restore", cmd_restore))
    app.add_handler(add_conv)
    app.add_handler(edit_conv)
    app.add_handler(MessageHandler(filters.Regex(r'^del:'), handle_delete))
    app.add_handler(MessageHandler(filters.Regex(r'^(sold:|hide:|restore:)'), handle_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))

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
        logger.info(f"Admin bot on port {PORT}")
        while True:
            await asyncio.sleep(3600)
    else:
        await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
