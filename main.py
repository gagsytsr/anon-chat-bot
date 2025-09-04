# main.py
import asyncio
import logging
import os
import re
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# Импортируем наши новые модули
import database
import keyboards

# ===== НАСТРОЙКИ ЛОГИРОВАНИЯ =====
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# ===== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ И КОНСТАНТЫ =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ADMIN_IDS = set()

if not BOT_TOKEN or not ADMIN_PASSWORD:
    logging.error("BOT_TOKEN или ADMIN_PASSWORD не установлены!")
    exit(1)

# Константы
REWARD_FOR_REFERRAL = 10
COST_FOR_18PLUS = 50
COST_FOR_UNBAN = 100
COST_FOR_PHOTO = 50
MAX_WARNINGS = 3

# ===== ВРЕМЕННЫЕ ДАННЫЕ (ХРАНЯТСЯ В ПАМЯТИ) =====
# Эти данные не нужно хранить после перезапуска
waiting_users = []
active_chats = {}
show_name_requests = {}
active_tasks = {}
user_interests = {} # Временно хранит выбор интересов

# Список интересов с эмодзи
available_interests = {
    "Музыка": "🎵", "Игры": "🎮", "Кино": "🎬",
    "Путешествия": "✈️", "Общение": "💬", "18+": "🔞"
}

# ====== ОБРАБОТЧИКИ КОМАНД ======

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    user = update.effective_user
    await database.ensure_user(user.id, user.username)

    # Реферальная система
    if context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user.id:
                # Убедимся, что пригласивший существует в БД
                await database.ensure_user(referrer_id)
                # add_referral вернет True, если реферал был новым
                if await database.add_referral(referrer_id, user.id):
                    await database.update_balance(referrer_id, REWARD_FOR_REFERRAL)
                    await context.bot.send_message(
                        referrer_id,
                        f"🎉 Новый пользователь по вашей ссылке! Вам начислено {REWARD_FOR_REFERRAL} валюты."
                    )
        except (ValueError, IndexError):
            pass

    await update.message.reply_text(
        "👋 Добро пожаловать в анонимный чат!\n\n"
        "⚠️ Перед началом подтвердите согласие с правилами:\n"
        "• Запрещено нарушать законы.\n"
        "• Соблюдайте уважение.\n\n"
        "Нажмите 'Согласен' чтобы начать.",
        reply_markup=keyboards.get_agreement_keyboard()
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /admin."""
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        await show_admin_menu(update)
    else:
        await update.message.reply_text("🔐 Введите пароль:")
        context.user_data["awaiting_admin_password"] = True

# ====== ОСНОВНЫЕ ФУНКЦИИ И МЕНЮ ======

async def show_main_menu(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет главное меню пользователю."""
    if await database.is_user_banned(user_id):
        await context.bot.send_message(
            user_id,
            "❌ Вы заблокированы. Чтобы получить доступ к боту, вы должны разблокировать себя.",
            reply_markup=keyboards.get_unban_keyboard(COST_FOR_UNBAN)
        )
    else:
        await context.bot.send_message(
            user_id, "Выберите действие:",
            reply_markup=keyboards.get_main_menu_keyboard()
        )

async def show_interests_menu(update: Update, user_id: int):
    """Показывает меню выбора интересов."""
    if await database.is_user_banned(user_id):
        await update.message.reply_text("❌ Вы заблокированы и не можете искать собеседников.")
        return
    if user_id in active_chats:
        await update.message.reply_text("❌ Вы уже в чате. Завершите его, чтобы начать новый.")
        return

    user_interests[user_id] = []
    await update.message.reply_text(
        "Выберите интересы, чтобы найти подходящего собеседника:",
        reply_markup=await keyboards.get_interests_keyboard(user_id, user_interests, available_interests)
    )

async def show_admin_menu(update: Update):
    """Показывает админ-панель."""
    await update.message.reply_text("🔐 Админ-панель", reply_markup=keyboards.get_admin_keyboard())

# ====== ЛОГИКА ЧАТА ======

async def find_partner(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Ищет собеседника по интересам."""
    user_interests_set = set(user_interests.get(user_id, []))
    
    for waiting_user_id in list(waiting_users):
        if waiting_user_id == user_id:
            continue
        waiting_user_interests_set = set(user_interests.get(waiting_user_id, []))
        if user_interests_set & waiting_user_interests_set:
            waiting_users.remove(waiting_user_id)
            await start_chat(context, user_id, waiting_user_id)
            return

    if user_id not in waiting_users:
        waiting_users.append(user_id)
        
    await context.bot.send_message(user_id, "⏳ Ищем собеседника с похожими интересами...")

async def start_chat(context: ContextTypes.DEFAULT_TYPE, u1: int, u2: int):
    """Начинает чат между двумя пользователями."""
    active_chats[u1], active_chats[u2] = u2, u1
    
    markup = keyboards.get_chat_keyboard()
    msg = "🎉 Собеседник найден! У вас есть 10 минут, чтобы решить, хотите ли вы обменяться никами."
    await context.bot.send_message(u1, msg, reply_markup=markup)
    await context.bot.send_message(u2, msg, reply_markup=markup)
    
    task = asyncio.create_task(chat_timer_task(context, u1, u2))
    pair_key = tuple(sorted((u1, u2)))
    active_tasks[pair_key] = task

async def end_chat(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Завершает чат для одного или двух пользователей."""
    if user_id in active_chats:
        partner_id = active_chats.pop(user_id)
        active_chats.pop(partner_id, None)

        pair_key = tuple(sorted((user_id, partner_id)))
        if pair_key in show_name_requests:
            del show_name_requests[pair_key]
        
        task = active_tasks.pop(pair_key, None)
        if task:
            task.cancel()

        await context.bot.send_message(user_id, "❌ Чат завершён.", reply_markup=ReplyKeyboardRemove())
        await context.bot.send_message(partner_id, "❌ Собеседник вышел.", reply_markup=ReplyKeyboardRemove())
        
        await show_main_menu(user_id, context)
        await show_main_menu(partner_id, context)

# ====== ЛОГИКА ОБМЕНА НИКАМИ ======

async def chat_timer_task(context, u1, u2):
    """Таймер, который через 10 минут предлагает обменяться никами."""
    try:
        await asyncio.sleep(600)
        if u1 in active_chats and active_chats[u1] == u2:
            await ask_to_show_name(context, u1, u2)
    except asyncio.CancelledError:
        pass

async def ask_to_show_name(context: ContextTypes.DEFAULT_TYPE, u1, u2):
    """Спрашивает пользователей, хотят ли они показать ники."""
    if u1 in active_chats and active_chats[u1] == u2:
        pair_key = tuple(sorted((u1, u2)))
        show_name_requests[pair_key] = {u1: None, u2: None}
        
        keyboard = keyboards.get_show_name_keyboard()
        msg = "⏳ Прошло 10 минут. Хотите показать свой ник собеседнику?"
        await context.bot.send_message(u1, msg, reply_markup=keyboard)
        await context.bot.send_message(u2, msg, reply_markup=keyboard)

async def handle_show_name_request(user_id: int, context: ContextTypes.DEFAULT_TYPE, agreement: bool):
    """Обрабатывает ответы на запрос о показе ника."""
    partner_id = active_chats.get(user_id)
    if not partner_id: return

    pair_key = tuple(sorted((user_id, partner_id)))
    if pair_key not in show_name_requests: return

    if not agreement:
        await context.bot.send_message(user_id, "Вы отказались. Чат будет завершён.")
        await context.bot.send_message(partner_id, "Собеседник отказался показывать ник. Чат будет завершён.")
        await end_chat(user_id, context)
        return

    show_name_requests[pair_key][user_id] = agreement
    responses = show_name_requests[pair_key]
    
    if all(responses.values()): # Если оба ответили "да"
        u1, u2 = pair_key
        u1_info = await context.bot.get_chat(u1)
        u2_info = await context.bot.get_chat(u2)
        
        u1_name = f"@{u1_info.username}" if u1_info.username else u1_info.first_name
        u2_name = f"@{u2_info.username}" if u2_info.username else u2_info.first_name
        
        await context.bot.send_message(u1, f"🥳 Собеседник согласился! Его ник: {u2_name}")
        await context.bot.send_message(u2, f"🥳 Собеседник согласился! Его ник: {u1_name}")
        
        del show_name_requests[pair_key]
        task = active_tasks.pop(pair_key, None)
        if task: task.cancel()

# ====== ОБРАБОТЧИК КНОПОК (CALLBACK) ======

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик всех inline-кнопок."""
    query = update.callback_query
    user = query.from_user
    await database.ensure_user(user.id, user.username)
    await query.answer()
    data = query.data

    # --- Основные кнопки ---
    if data == "agree":
        await query.message.delete()
        await show_main_menu(user.id, context)

    elif data == "unban_request":
        balance = await database.get_balance(user.id)
        if balance >= COST_FOR_UNBAN:
            await database.update_balance(user.id, -COST_FOR_UNBAN)
            await database.unban_user(user.id)
            await query.edit_message_text(f"✅ Вы успешно разблокированы! Ваш баланс: {await database.get_balance(user.id)}.")
            await show_main_menu(user.id, context)
        else:
            await query.edit_message_text(f"❌ Недостаточно валюты. Необходимо {COST_FOR_UNBAN}.")

    # --- Выбор интересов ---
    elif data.startswith("interest_"):
        interest_key = data.replace("interest_", "")
        if interest_key in user_interests.get(user.id, []):
            user_interests[user.id].remove(interest_key)
        else:
            user_interests.setdefault(user.id, []).append(interest_key)
        await query.edit_message_reply_markup(
            reply_markup=await keyboards.get_interests_keyboard(user.id, user_interests, available_interests)
        )

    elif data == "interests_done":
        selected = user_interests.get(user.id, [])
        if not selected:
            await query.edit_message_text("❌ Пожалуйста, выберите хотя бы один интерес.",
                reply_markup=await keyboards.get_interests_keyboard(user.id, user_interests, available_interests))
            return
        
        if "18+" in selected and not await database.has_unlocked_18plus(user.id):
            balance = await database.get_balance(user.id)
            if balance >= COST_FOR_18PLUS:
                await database.update_balance(user.id, -COST_FOR_18PLUS)
                await database.unlock_18plus(user.id)
                await query.edit_message_text(f"✅ Чат 18+ разблокирован за {COST_FOR_18PLUS} валюты! Ищем собеседника...")
            else:
                await query.edit_message_text(f"❌ Недостаточно валюты для 18+ (нужно {COST_FOR_18PLUS}).")
                user_interests[user.id].remove("18+")
                return
        else:
            await query.edit_message_text(f"✅ Интересы выбраны. Ищем собеседника...")
        
        await find_partner(context, user.id)

    # --- Обмен никами ---
    elif data == "show_name_yes":
        await query.message.edit_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ Вы согласились. Ожидаем ответа собеседника...")
        await handle_show_name_request(user.id, context, True)
    
    elif data == "show_name_no":
        await query.message.edit_reply_markup(reply_markup=None)
        await handle_show_name_request(user.id, context, False)

    # --- Жалобы ---
    elif data.startswith("report_reason_"):
        # Логика жалоб (остается без изменений)
        pass
    
    # --- Админка ---
    elif data == "admin_ban":
        await query.message.reply_text("Введите ID для бана:")
        context.user_data["awaiting_ban_id"] = True
    # ... и другие админ-кнопки

# ====== ОБРАБОТЧИК СООБЩЕНИЙ ======

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовые сообщения."""
    user = update.effective_user
    await database.ensure_user(user.id, user.username)
    text = update.message.text

    if await database.is_user_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы.")
        return
        
    # --- Логика админ-ввода ---
    if context.user_data.get("awaiting_ban_id"):
        try:
            target_id = int(text)
            await database.ensure_user(target_id)
            await database.ban_user(target_id)
            await update.message.reply_text(f"✅ Пользователь {target_id} забанен.")
            await context.bot.send_message(target_id, "❌ Вы были заблокированы администратором.")
        except ValueError:
            await update.message.reply_text("❌ Неверный ID.")
        context.user_data.pop("awaiting_ban_id", None)
        return

    # --- Команды из меню ---
    if text == "🔍 Поиск собеседника":
        await show_interests_menu(update, user.id)
    elif text == "💰 Мой баланс":
        balance = await database.get_balance(user.id)
        await update.message.reply_text(f"💰 Ваш текущий баланс: {balance}")
    elif text == "🔗 Мои рефералы":
        count = await database.get_referral_count(user.id)
        link = f"https://t.me/{context.bot.username}?start={user.id}"
        await update.message.reply_text(f"🔗 Ваша ссылка: {link}\n👥 Приглашено: {count}")

    # --- Логика в чате ---
    elif user.id in active_chats:
        partner_id = active_chats[user.id]
        if text == "🚫 Завершить чат":
            await end_chat(user.id, context)
        elif text == "🔍 Начать новый чат":
            await end_chat(user.id, context)
            await show_interests_menu(update, user.id)
        elif text == "⚠️ Пожаловаться":
            await update.message.reply_text("Выберите причину:", reply_markup=keyboards.get_report_reasons_keyboard())
        else:
            # Проверка на разглашение личной информации
            if re.search(r'@?\s*[A-Za-z0-9_]{5,}', text):
                warnings = await database.increment_warnings(user.id)
                if warnings >= MAX_WARNINGS:
                    await database.ban_user(user.id)
                    await update.message.reply_text("❌ Вы забанены за многократные попытки разгласить личную информацию.")
                    await context.bot.send_message(partner_id, "❌ Собеседник был забанен за нарушение правил.")
                    await end_chat(user.id, context)
                else:
                    await update.message.reply_text(f"⚠️ Предупреждение {warnings}/{MAX_WARNINGS}: Нельзя разглашать личную информацию.")
            else:
                await context.bot.send_message(partner_id, text)

# ====== ЗАПУСК БОТА ======
async def main():
    """Основная функция запуска бота."""
    try:
        await database.init_db()
    except Exception as e:
        logging.critical(f"Не удалось подключиться к базе данных! Бот не может быть запущен. Ошибка: {e}")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    # app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.VOICE, media_handler))

    logging.info("Бот запускается...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())

