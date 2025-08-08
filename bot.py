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

# ===== НАСТРОЙКИ ЛОГИРОВАНИЯ =====
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

# Словари для хранения информации
waiting_users = []
active_chats = {}
show_name_requests = {}
user_agreements = {}
banned_users = set()
reported_users = {}
search_timeouts = {}
user_interests = {}
referrals = {}
invited_by = {}
# Новый словарь для хранения баланса пользователей
user_balance = {}

# Обновленный список интересов с эмодзи
available_interests = {
    "Музыка": "🎵", "Игры": "🎮", "Кино": "🎬",
    "Путешествия": "✈️", "Общение": "💬", "18+": "🔞"
}

# ===== КОНСТАНТЫ =====
REWARD_FOR_REFERRAL = 10
COST_FOR_18PLUS = 50

# ====== СТАРТ ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /start.
    """
    user_id = update.effective_user.id
    if user_id in banned_users:
        await update.message.reply_text("❌ Вы заблокированы.")
        return

    # Инициализируем баланс для нового пользователя
    if user_id not in user_balance:
        user_balance[user_id] = 0

    # Логика для реферальной ссылки
    if context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user_id and user_id not in invited_by:
                referrals[referrer_id] = referrals.get(referrer_id, 0) + 1
                invited_by[user_id] = referrer_id
                # Начисляем валюту рефереру
                user_balance[referrer_id] = user_balance.get(referrer_id, 0) + REWARD_FOR_REFERRAL
                await context.bot.send_message(referrer_id, f"🎉 Новый пользователь по вашей ссылке! Вам начислено {REWARD_FOR_REFERRAL} валюты.")
        except (ValueError, IndexError):
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
    """
    Обработчик всех кнопок Inline.
    """
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data == "agree":
        user_agreements[user_id] = True
        await show_main_menu(user_id, context)

    elif data.startswith("interest_"):
        interest_key = data.replace("interest_", "")
        if interest_key in user_interests.get(user_id, []):
            user_interests[user_id].remove(interest_key)
        else:
            user_interests.setdefault(user_id, []).append(interest_key)

        await update_interests_menu(user_id, query)

    elif data == "interests_done":
        selected_interests = user_interests.get(user_id, [])
        interest_names = [name for name, _ in available_interests.items() if name in selected_interests]

        # Проверяем, если выбран чат 18+, и у пользователя не хватает валюты
        if "18+" in selected_interests and user_balance.get(user_id, 0) < COST_FOR_18PLUS:
            await query.edit_message_text(f"❌ Недостаточно валюты для чата 18+ (необходимо {COST_FOR_18PLUS}). Ваш баланс: {user_balance.get(user_id, 0)}.")
            user_interests[user_id].remove("18+")
            return

        await query.edit_message_text(
            f"✅ Ваши интересы: {', '.join(interest_names) or 'Не выбраны'}.\nИщем собеседника..."
        )
        await find_partner(context, user_id)

    elif data == "show_name_yes":
        await handle_show_name_request(user_id, context, True)

    elif data == "show_name_no":
        await handle_show_name_request(user_id, context, False)

    # ==== АДМИНКА ====
    elif data == "admin_stats":
        total_users = len([u for u in user_agreements if user_agreements[u]])
        active_pairs = len(active_chats) // 2
        await query.message.reply_text(
            f"📊 Пользователей: {total_users}\n💬 Активных чатов: {active_pairs}\n"
            f"⚠️ Жалоб: {len(reported_users)}\n⛔ Забанено: {len(banned_users)}\n"
            f"🔗 Рефералов: {sum(referrals.values())}\n💰 Общий баланс: {sum(user_balance.values())}"
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

    elif data == "admin_add_currency":
        await query.message.reply_text("Введите ID и сумму через пробел (например, 123456789 100):")
        context.user_data["awaiting_add_currency"] = True

    elif data == "admin_remove_currency":
        await query.message.reply_text("Введите ID и сумму через пробел (например, 123456789 50):")
        context.user_data["awaiting_remove_currency"] = True

    elif data == "admin_exit":
        ADMIN_IDS.discard(user_id)
        await query.message.reply_text("🚪 Вы вышли из админ-панели.", reply_markup=ReplyKeyboardRemove())

# ====== МЕНЮ ИНТЕРЕСОВ ======
async def update_interests_menu(user_id, query):
    """
    Обновляет кнопки выбора интересов.
    """
    keyboard = []
    selected_interests = user_interests.get(user_id, [])
    for interest, emoji in available_interests.items():
        text = f"✅ {interest} {emoji}" if interest in selected_interests else f"{interest} {emoji}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"interest_{interest}")])
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

# ====== МЕНЮ ОСНОВНОЕ ======
async def show_main_menu(user_id, context):
    """
    Отправляет главное меню пользователю.
    """
    # Добавляем кнопку "Мой баланс"
    keyboard = [["🔍 Поиск собеседника"], ["💰 Мой баланс"], ["⚠️ Сообщить о проблеме"], ["🔗 Мои рефералы"]]
    await context.bot.send_message(user_id, "Выберите действие:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

# ====== ПОИСК СОБЕСЕДНИКА ======
async def show_interests_menu(update, user_id):
    """
    Показывает меню выбора интересов.
    """
    user_interests[user_id] = []
    keyboard = [[InlineKeyboardButton(f"{interest} {emoji}", callback_data=f"interest_{interest}")] for interest, emoji in available_interests.items()]
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    await update.message.reply_text("Выберите интересы, чтобы найти подходящего собеседника:", reply_markup=InlineKeyboardMarkup(keyboard))

async def find_partner(context, user_id):
    """
    Ищет собеседника по интересам.
    """
    user_interests_set = set(user_interests.get(user_id, []))
    
    # Сначала проверяем, есть ли уже кто-то в очереди с совпадающими интересами
    for waiting_user_id in list(waiting_users):
        waiting_user_interests_set = set(user_interests.get(waiting_user_id, []))
        if user_interests_set & waiting_user_interests_set:
            waiting_users.remove(waiting_user_id)
            # Если выбран чат 18+, списываем валюту
            if "18+" in user_interests_set:
                user_balance[user_id] -= COST_FOR_18PLUS
                user_balance[waiting_user_id] -= COST_FOR_18PLUS
            await start_chat(context, user_id, waiting_user_id)
            return

    # Если совпадений нет, добавляем пользователя в очередь
    if user_id not in waiting_users:
        waiting_users.append(user_id)
        
    await context.bot.send_message(user_id, "⏳ Ищем собеседника с похожими интересами...")

async def start_chat(context, u1, u2):
    """
    Начинает чат между двумя пользователями.
    """
    active_chats[u1] = u2
    active_chats[u2] = u1
    
    markup = ReplyKeyboardMarkup(
        [["🚫 Завершить чат"], ["🔍 Начать новый чат"]],
        resize_keyboard=True
    )
    
    await context.bot.send_message(u1, "🎉 Собеседник найден! У вас есть 10 минут, чтобы решить, хотите ли вы обменяться никами.", reply_markup=markup)
    await context.bot.send_message(u2, "🎉 Собеседник найден! У вас есть 10 минут, чтобы решить, хотите ли вы обменяться никами.", reply_markup=markup)
    
    context.job_queue.run_once(ask_to_show_name, 600, chat_id=u1, context={"u1": u1, "u2": u2})

async def ask_to_show_name(context: ContextTypes.DEFAULT_TYPE):
    """
    Спрашивает пользователей, хотят ли они показать ники, через 10 минут.
    """
    u1 = context.job.context["u1"]
    u2 = context.job.context["u2"]
    
    if u1 in active_chats and active_chats[u1] == u2:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, показать ник", callback_data="show_name_yes")],
            [InlineKeyboardButton("❌ Нет, не показывать", callback_data="show_name_no")]
        ])
        
        show_name_requests[(u1, u2)] = {u1: None, u2: None}
        
        await context.bot.send_message(u1, "⏳ Прошло 10 минут. Хотите показать свой ник собеседнику?", reply_markup=keyboard)
        await context.bot.send_message(u2, "⏳ Прошло 10 минут. Хотите показать свой ник собеседнику?", reply_markup=keyboard)

async def handle_show_name_request(user_id, context, agreement):
    """
    Обрабатывает ответы на запрос о показе ника.
    """
    partner_id = active_chats.get(user_id)
    if not partner_id:
        return

    pair_key = tuple(sorted((user_id, partner_id)))
    
    if pair_key not in show_name_requests:
        return
        
    show_name_requests[pair_key][user_id] = agreement
    
    u1_agree = show_name_requests[pair_key].get(pair_key[0])
    u2_agree = show_name_requests[pair_key].get(pair_key[1])
    
    if u1_agree is not None and u2_agree is not None:
        if u1_agree and u2_agree:
            u1_name = (await context.bot.get_chat(pair_key[0])).first_name
            u2_name = (await context.bot.get_chat(pair_key[1])).first_name
            
            await context.bot.send_message(pair_key[0], f"🥳 Отлично! Собеседник согласился. Его ник: {u2_name}")
            await context.bot.send_message(pair_key[1], f"🥳 Отлично! Собеседник согласился. Его ник: {u1_name}")
        else:
            await context.bot.send_message(pair_key[0], "😔 Собеседник отказался. Чат остаётся анонимным.")
            await context.bot.send_message(pair_key[1], "😔 Собеседник отказался. Чат остаётся анонимным.")
            
        del show_name_requests[pair_key]

# ====== ОБРАБОТЧИК СООБЩЕНИЙ ======
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает текстовые сообщения и команды.
    """
    user_id = update.effective_user.id
    text = update.message.text

    # Обработка админ-команд
    if context.user_data.get("awaiting_admin_password"):
        if text.strip() == ADMIN_PASSWORD:
            ADMIN_IDS.add(user_id)
            await show_admin_menu(update)
        else:
            await update.message.reply_text("❌ Неверный пароль.")
        context.user_data["awaiting_admin_password"] = False
        return

    if context.user_data.get("awaiting_ban_id"):
        try:
            target_id = int(text)
            banned_users.add(target_id)
            await update.message.reply_text(f"✅ Пользователь {target_id} забанен.")
        except ValueError:
            await update.message.reply_text("❌ Неверный ID.")
        context.user_data.pop("awaiting_ban_id")
        return

    if context.user_data.get("awaiting_unban_id"):
        try:
            target_id = int(text)
            banned_users.discard(target_id)
            await update.message.reply_text(f"✅ Пользователь {target_id} разбанен.")
        except ValueError:
            await update.message.reply_text("❌ Неверный ID.")
        context.user_data.pop("awaiting_unban_id")
        return

    if context.user_data.get("awaiting_add_currency"):
        try:
            target_id, amount = map(int, text.split())
            user_balance[target_id] = user_balance.get(target_id, 0) + amount
            await update.message.reply_text(f"✅ Пользователю {target_id} начислено {amount} валюты. Новый баланс: {user_balance[target_id]}.")
            await context.bot.send_message(target_id, f"🎉 Администратор начислил вам {amount} валюты. Ваш баланс: {user_balance[target_id]}.")
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Неверный формат. Попробуйте еще раз.")
        context.user_data.pop("awaiting_add_currency")
        return

    if context.user_data.get("awaiting_remove_currency"):
        try:
            target_id, amount = map(int, text.split())
            user_balance[target_id] = user_balance.get(target_id, 0) - amount
            user_balance[target_id] = max(0, user_balance[target_id]) # Баланс не может быть отрицательным
            await update.message.reply_text(f"✅ У пользователя {target_id} изъято {amount} валюты. Новый баланс: {user_balance[target_id]}.")
            await context.bot.send_message(target_id, f"⚠️ Администратор изъял у вас {amount} валюты. Ваш баланс: {user_balance[target_id]}.")
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Неверный формат. Попробуйте еще раз.")
        context.user_data.pop("awaiting_remove_currency")
        return

    # Обработка команд из главного меню
    if text == "🔍 Поиск собеседника":
        await show_interests_menu(update, user_id)
    elif text == "⚠️ Сообщить о проблеме":
        await update.message.reply_text("⚠️ Жалоба отправлена админам.")
        for admin in ADMIN_IDS:
            await context.bot.send_message(admin, f"❗ Жалоба от {user_id}")
    elif text == "🔗 Мои рефералы":
        link = f"https://t.me/{context.bot.username}?start={user_id}"
        await update.message.reply_text(f"🔗 Ваша ссылка: {link}\n👥 Приглашено: {referrals.get(user_id, 0)}")
    elif text == "💰 Мой баланс":
        balance = user_balance.get(user_id, 0)
        await update.message.reply_text(f"💰 Ваш текущий баланс: {balance}")

    # Обработка команд из чата
    elif user_id in active_chats:
        if text == "🚫 Завершить чат":
            await end_chat(user_id, context)
        elif text == "🔍 Начать новый чат":
            await end_chat(user_id, context)
            await show_interests_menu(update, user_id)
        else:
            partner_id = active_chats[user_id]
            await context.bot.send_message(partner_id, text)

# ====== ОБРАБОТЧИК МЕДИА ======
async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает отправку фото, видео и т.д.
    """
    user_id = update.effective_user.id
    if user_id in active_chats:
        partner = active_chats[user_id]
        if update.message.photo:
            await context.bot.send_photo(partner, update.message.photo[-1].file_id)
        elif update.message.video:
            await context.bot.send_video(partner, update.message.video.file_id)
        elif update.message.voice:
            await context.bot.send_voice(partner, update.message.voice.file_id)

# ====== КОМАНДА АДМИНА ======
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /admin.
    """
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        await show_admin_menu(update)
    else:
        await update.message.reply_text("🔐 Введите пароль:")
        context.user_data["awaiting_admin_password"] = True

async def show_admin_menu(update: Update):
    """
    Показывает админ-панель.
    """
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("💰 Выдать валюту", callback_data="admin_add_currency")],
        [InlineKeyboardButton("💸 Забрать валюту", callback_data="admin_remove_currency")],
        [InlineKeyboardButton("🚫 Завершить все чаты", callback_data="admin_stop_all")],
        [InlineKeyboardButton("👮‍♂️ Забанить", callback_data="admin_ban")],
        [InlineKeyboardButton("🔓 Разбанить", callback_data="admin_unban")],
        [InlineKeyboardButton("🚪 Выйти", callback_data="admin_exit")]
    ])
    await update.message.reply_text("🔐 Админ-панель", reply_markup=kb)

# ====== ЗАВЕРШЕНИЕ ЧАТА ======
async def end_chat(user_id, context):
    """
    Завершает чат для двух пользователей.
    """
    if user_id in active_chats:
        partner = active_chats.pop(user_id)
        active_chats.pop(partner, None)

        pair_key = tuple(sorted((user_id, partner)))
        if pair_key in show_name_requests:
            del show_name_requests[pair_key]

        await context.bot.send_message(user_id, "❌ Чат завершён.", reply_markup=ReplyKeyboardRemove())
        await context.bot.send_message(partner, "❌ Собеседник вышел.", reply_markup=ReplyKeyboardRemove())

        await show_main_menu(user_id, context)
        await show_main_menu(partner, context)

# ====== ЗАПУСК БОТА ======
async def main():
    """
    Основная функция запуска бота.
    """
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
