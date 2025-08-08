import asyncio
import logging
import os
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# ===== ЛОГИРОВАНИЕ =====
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ===== ПЕРЕМЕННЫЕ =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ADMIN_IDS = set()

if not BOT_TOKEN or not ADMIN_PASSWORD:
    logging.error("BOT_TOKEN или ADMIN_PASSWORD не установлены!")
    exit(1)

waiting_users = []
active_chats = {}
show_name_requests = {}
user_agreements = {}
banned_users = set()
reported_users = {}
search_timeouts = {}
user_interests = {}
available_interests = ["Музыка", "Игры", "Кино", "Путешествия", "Спорт", "Книги"]
referrals = {}
invited_by = {}

# ====== СТАРТ ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in banned_users:
        await update.message.reply_text("❌ Вы заблокированы.")
        return

    # Реферальная ссылка
    if context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user_id and user_id not in invited_by:
                referrals[referrer_id] = referrals.get(referrer_id, 0) + 1
                invited_by[user_id] = referrer_id
                await context.bot.send_message(referrer_id, "🎉 Новый пользователь по вашей ссылке!")
        except:
            pass

    user_agreements[user_id] = False
    keyboard = [[InlineKeyboardButton("✅ Согласен", callback_data="agree")]]
    await update.message.reply_text(
        "👋 Добро пожаловать в анонимный чат!\n\n"
        "⚠️ Перед началом подтвердите согласие с правилами:\n"
        "• Запрещено нарушать законы.\n"
        "• Соблюдайте уважение.\n\n"
        "Нажмите 'Согласен' чтобы начать.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ====== CALLBACK ОБРАБОТЧИК ======
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data == "agree":
        user_agreements[user_id] = True
        await show_main_menu(user_id, context)

    elif data.startswith("interest_"):
        interest = data.replace("interest_", "")
        if interest in user_interests.get(user_id, []):
            user_interests[user_id].remove(interest)
        else:
            user_interests.setdefault(user_id, []).append(interest)

        await update_interests_menu(user_id, query)

    elif data == "interests_done":
        await query.edit_message_text(
            f"✅ Ваши интересы: {', '.join(user_interests.get(user_id, [])) or 'Не выбраны'}.\nИщем собеседника..."
        )
        waiting_users.append(user_id)
        await find_partner(context)

    # ==== АДМИНКА ====
    elif data == "admin_stats":
        total_users = len([u for u in user_agreements if user_agreements[u]])
        active_pairs = len(active_chats) // 2
        await query.message.reply_text(
            f"📊 Пользователей: {total_users}\n💬 Активных чатов: {active_pairs}\n"
            f"⚠️ Жалоб: {len(reported_users)}\n⛔ Забанено: {len(banned_users)}\n"
            f"🔗 Рефералов: {sum(referrals.values())}"
        )

    elif data == "admin_stop_all":
        for uid in list(active_chats.keys()):
            await end_chat(uid, context)
        await query.message.reply_text("🚫 Все чаты завершены.")

    elif data == "admin_ban":
        await query.message.reply_text("Введите ID для бана:")
        context.user_data["awaiting_ban_id"] = True

    elif data == "admin_unban":
        await query.message.reply_text("Введите ID для разбана:")
        context.user_data["awaiting_unban_id"] = True

    elif data == "admin_exit":
        ADMIN_IDS.discard(user_id)
        await query.message.reply_text("🚪 Вы вышли из админ-панели.", reply_markup=ReplyKeyboardRemove())

# ====== МЕНЮ ИНТЕРЕСОВ ======
async def update_interests_menu(user_id, query):
    keyboard = []
    for interest in available_interests:
        text = f"✅ {interest}" if interest in user_interests.get(user_id, []) else interest
        keyboard.append([InlineKeyboardButton(text, callback_data=f"interest_{interest}")])
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

# ====== МЕНЮ ОСНОВНОЕ ======
async def show_main_menu(user_id, context):
    keyboard = [["🔍 Поиск собеседника"], ["⚠️ Сообщить о проблеме"], ["🔗 Мои рефералы"]]
    await context.bot.send_message(user_id, "Выберите действие:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

# ====== ПОИСК ======
async def show_interests_menu(update, user_id):
    keyboard = [[InlineKeyboardButton(i, callback_data=f"interest_{i}")] for i in available_interests]
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    user_interests[user_id] = []
    await update.message.reply_text("Выберите интересы:", reply_markup=InlineKeyboardMarkup(keyboard))

async def find_partner(context):
    if len(waiting_users) >= 2:
        u1 = waiting_users.pop(0)
        u2 = waiting_users.pop(0)
        active_chats[u1] = u2
        active_chats[u2] = u1
        show_name_requests[(u1, u2)] = {u1: None, u2: None}
        markup = ReplyKeyboardMarkup(
            [["🚫 Завершить чат", "🔍 Начать новый чат"], ["👤 Показать мой ник", "🙈 Не показывать ник"]],
            resize_keyboard=True
        )
        await context.bot.send_message(u1, "👤 Собеседник найден!", reply_markup=markup)
        await context.bot.send_message(u2, "👤 Собеседник найден!", reply_markup=markup)

# ====== ЧАТ ======
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # Пароль админа
    if context.user_data.get("awaiting_admin_password"):
        if text.strip() == ADMIN_PASSWORD:
            ADMIN_IDS.add(user_id)
            await show_admin_menu(update)
        else:
            await update.message.reply_text("❌ Неверный пароль.")
        context.user_data["awaiting_admin_password"] = False
        return

    # Бан/Разбан
    if context.user_data.get("awaiting_ban_id"):
        try:
            target_id = int(text)
            banned_users.add(target_id)
            await update.message.reply_text(f"✅ Пользователь {target_id} забанен.")
        except:
            await update.message.reply_text("❌ Неверный ID.")
        context.user_data.pop("awaiting_ban_id")
        return

    if context.user_data.get("awaiting_unban_id"):
        try:
            target_id = int(text)
            banned_users.discard(target_id)
            await update.message.reply_text(f"✅ Пользователь {target_id} разбанен.")
        except:
            await update.message.reply_text("❌ Неверный ID.")
        context.user_data.pop("awaiting_unban_id")
        return

    if text == "🔍 Поиск собеседника":
        await show_interests_menu(update, user_id)
    elif text == "⚠️ Сообщить о проблеме":
        await update.message.reply_text("⚠️ Жалоба отправлена админам.")
        for admin in ADMIN_IDS:
            await context.bot.send_message(admin, f"❗ Жалоба от {user_id}")
    elif text == "🚫 Завершить чат":
        await end_chat(user_id, context)
    elif text == "🔗 Мои рефералы":
        link = f"https://t.me/{context.bot.username}?start={user_id}"
        await update.message.reply_text(f"🔗 Ваша ссылка: {link}\n👥 Приглашено: {referrals.get(user_id, 0)}")
    elif user_id in active_chats:
        await context.bot.send_message(active_chats[user_id], text)

# ====== МЕДИА ======
async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_chats:
        partner = active_chats[user_id]
        if update.message.photo:
            await context.bot.send_photo(partner, update.message.photo[-1].file_id)

# ====== КОМАНДА АДМИН ======
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        await show_admin_menu(update)
    else:
        await update.message.reply_text("🔐 Введите пароль:")
        context.user_data["awaiting_admin_password"] = True

async def show_admin_menu(update: Update):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("🚫 Завершить все чаты", callback_data="admin_stop_all")],
        [InlineKeyboardButton("👮‍♂️ Забанить", callback_data="admin_ban")],
        [InlineKeyboardButton("🔓 Разбанить", callback_data="admin_unban")],
        [InlineKeyboardButton("🚪 Выйти", callback_data="admin_exit")]
    ])
    await update.message.reply_text("🔐 Админ-панель", reply_markup=kb)

# ====== ЗАВЕРШЕНИЕ ЧАТА ======
async def end_chat(user_id, context):
    if user_id in active_chats:
        partner = active_chats.pop(user_id)
        active_chats.pop(partner, None)
        await context.bot.send_message(user_id, "❌ Чат завершён.")
        await context.bot.send_message(partner, "❌ Собеседник вышел.")

# ====== ЗАПУСК ======
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.VOICE, media_handler))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
