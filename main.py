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
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD") # Оставим для обратной совместимости, но лучше использовать ADMIN_IDS
# ID администраторов можно задать через переменную окружения, перечислив их через запятую
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = {int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',') if admin_id.strip()}


if not BOT_TOKEN:
    logging.error("BOT_TOKEN не установлен! Бот не может быть запущен.")
    exit(1)

# Константы
REWARD_FOR_REFERRAL = 10
COST_FOR_18PLUS = 50
COST_FOR_UNBAN = 100
MAX_WARNINGS = 3

# ===== ВРЕМЕННЫЕ ДАННЫЕ (ХРАНЯТСЯ В ПАМЯТИ) =====
# Данные о таймерах/задачах. Их нельзя хранить в БД.
active_tasks = {}

# Список доступных интересов
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
    if context.args and context.args[0].isdigit():
        referrer_id = int(context.args[0])
        if referrer_id != user.id:
            await database.ensure_user(referrer_id) 
            if await database.add_referral(referrer_id, user.id):
                await database.update_balance(referrer_id, REWARD_FOR_REFERRAL)
                try:
                    await context.bot.send_message(
                        referrer_id,
                        f"🎉 Новый пользователь @{user.username} присоединился по вашей ссылке! Вам начислено {REWARD_FOR_REFERRAL} валюты."
                    )
                except Exception as e:
                    logging.warning(f"Не удалось отправить уведомление рефереру {referrer_id}: {e}")
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
    elif ADMIN_PASSWORD: # Оставим вход по паролю, если он задан
        await update.message.reply_text("🔐 Введите пароль администратора:")
        context.user_data["awaiting_admin_password"] = True
    else:
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")

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
            user_id, "⬇️ Выберите действие из меню:",
            reply_markup=keyboards.get_main_menu_keyboard()
        )

async def show_interests_menu(update: Update, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню выбора интересов."""
    if await database.is_user_banned(user_id):
        await update.message.reply_text("❌ Вы заблокированы и не можете искать собеседников.")
        return
    
    if await database.get_partner_id(user_id):
        await update.message.reply_text("❌ Вы уже в чате. Завершите его, чтобы начать новый.")
        return
    
    context.user_data['selected_interests'] = []
    await update.message.reply_text(
        "Выберите ваши интересы, чтобы найти подходящего собеседника:",
        reply_markup=await keyboards.get_interests_keyboard(user_id, {user_id: []}, available_interests)
    )

async def show_admin_menu(update: Update):
    """Показывает админ-панель."""
    await update.message.reply_text("🔐 Админ-панель", reply_markup=keyboards.get_admin_keyboard())

# ====== ЛОГИКА ЧАТА ======

async def start_search_logic(user_id: int, interests: list, context: ContextTypes.DEFAULT_TYPE):
    """Основная логика поиска собеседника."""
    partner_id = await database.find_partner_in_queue(user_id, interests)
    
    if partner_id:
        await database.remove_from_search_queue(partner_id)
        await start_chat(context, user_id, partner_id)
    else:
        await database.add_to_search_queue(user_id, interests)
        await context.bot.send_message(user_id, "⏳ Ищем собеседника с похожими интересами...")

async def start_chat(context: ContextTypes.DEFAULT_TYPE, u1: int, u2: int):
    """Начинает чат между двумя пользователями."""
    await database.create_chat(u1, u2)
    
    markup = keyboards.get_chat_keyboard()
    msg = "🎉 Собеседник найден! Начинайте общение."
    await context.bot.send_message(u1, msg, reply_markup=markup)
    await context.bot.send_message(u2, msg, reply_markup=markup)

async def end_chat(user_id: int, context: ContextTypes.DEFAULT_TYPE, initiator_message: str, partner_message: str):
    """Завершает чат для двух пользователей."""
    chat_pair = await database.delete_chat(user_id)
    if chat_pair:
        u1, u2 = chat_pair
        
        initiator_id = user_id
        partner_id = u2 if u1 == user_id else u1

        await context.bot.send_message(initiator_id, initiator_message, reply_markup=ReplyKeyboardRemove())
        await show_main_menu(initiator_id, context)
        
        await context.bot.send_message(partner_id, partner_message, reply_markup=ReplyKeyboardRemove())
        await show_main_menu(partner_id, context)

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
        selected = context.user_data.get('selected_interests', [])
        
        if interest_key in selected:
            selected.remove(interest_key)
        else:
            selected.append(interest_key)
        context.user_data['selected_interests'] = selected

        temp_user_interests = {user.id: selected}
        
        await query.edit_message_reply_markup(
            reply_markup=await keyboards.get_interests_keyboard(user.id, temp_user_interests, available_interests)
        )

    elif data == "interests_done":
        selected = context.user_data.get('selected_interests', [])
        if not selected:
            await query.answer("❌ Пожалуйста, выберите хотя бы один интерес.", show_alert=True)
            return
        
        if "18+" in selected and not await database.has_unlocked_18plus(user.id):
            balance = await database.get_balance(user.id)
            if balance >= COST_FOR_18PLUS:
                await database.update_balance(user.id, -COST_FOR_18PLUS)
                await database.unlock_18plus(user.id)
                await query.edit_message_text(f"✅ Чат 18+ разблокирован за {COST_FOR_18PLUS} валюты!")
            else:
                await query.answer(f"❌ Недостаточно валюты для 18+ (нужно {COST_FOR_18PLUS}).", show_alert=True)
                context.user_data.get('selected_interests', []).remove("18+")
                return
        
        await query.edit_message_text(f"✅ Интересы выбраны: {', '.join(selected)}. Начинаем поиск...")
        await start_search_logic(user.id, selected, context)
        context.user_data.pop('selected_interests', None)
    
    # --- Логика админки ---
    elif data == "admin_ban":
        if user.id in ADMIN_IDS:
            await query.message.reply_text("Введите ID пользователя для бана:")
            context.user_data["awaiting_ban_id"] = True
    # Добавьте здесь обработку других админ-кнопок по аналогии

# ====== ОБРАБОТЧИК СООБЩЕНИЙ ======
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовые сообщения."""
    user = update.effective_user
    text = update.message.text
    await database.ensure_user(user.id, user.username)

    if await database.is_user_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы.")
        return

    # --- Логика админ-ввода ---
    if context.user_data.get("awaiting_admin_password"):
        if text == ADMIN_PASSWORD:
            ADMIN_IDS.add(user.id)
            await update.message.reply_text("✅ Пароль верный. Доступ предоставлен.")
            await show_admin_menu(update)
        else:
            await update.message.reply_text("❌ Неверный пароль.")
        context.user_data.pop("awaiting_admin_password")
        return

    if context.user_data.get("awaiting_ban_id"):
        if user.id in ADMIN_IDS:
            try:
                target_id = int(text)
                await database.ensure_user(target_id)
                await database.ban_user(target_id)
                await update.message.reply_text(f"✅ Пользователь {target_id} забанен.")
                await context.bot.send_message(target_id, "❌ Вы были заблокированы администратором.")
            except ValueError:
                await update.message.reply_text("❌ Неверный ID.")
            except Exception as e:
                await update.message.reply_text(f"❌ Произошла ошибка: {e}")
            context.user_data.pop("awaiting_ban_id")
        return

    # --- Логика в чате ---
    partner_id = await database.get_partner_id(user.id)
    if partner_id:
        if text == "🚫 Завершить чат":
            await end_chat(user.id, context, "❌ Вы завершили чат.", "❌ Собеседник вышел из чата.")
        elif text == "🔍 Начать новый чат":
            await end_chat(user.id, context, "❌ Чат завершен. Начинаем новый поиск.", "❌ Собеседник решил начать новый поиск.")
            await show_interests_menu(update, user.id, context)
        elif text == "⚠️ Пожаловаться":
            await update.message.reply_text("Выберите причину:", reply_markup=keyboards.get_report_reasons_keyboard())
        else:
            # Пересылка сообщения
            await context.bot.send_message(partner_id, text)
        return

    # --- Команды из меню ---
    if text == "🔍 Поиск собеседника":
        await show_interests_menu(update, user.id, context)
    elif text == "💰 Мой баланс":
        balance = await database.get_balance(user.id)
        await update.message.reply_text(f"💰 Ваш текущий баланс: {balance}")
    elif text == "🔗 Мои рефералы":
        count = await database.get_referral_count(user.id)
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start={user.id}"
        await update.message.reply_text(f"🔗 Ваша реферальная ссылка:\n`{link}`\n\n👥 Приглашено пользователей: {count}", parse_mode='MarkdownV2')
    else:
        # Если пользователь не в чате и сообщение не команда
        await update.message.reply_text("Используйте кнопки меню для навигации.", reply_markup=keyboards.get_main_menu_keyboard())

# ====== ЗАПУСК БОТА ======
async def main():
    """Основная функция запуска бота."""
    try:
        await database.init_db()
    except Exception as e:
        logging.critical(f"Не удалось подключиться к базе данных! Бот не может быть запущен. Ошибка: {e}")
        return
    
    # При запуске очищаем старые сессии, если они зависли
    async with database.db_pool.acquire() as conn:
        await conn.execute("DELETE FROM search_queue;")
        await conn.execute("DELETE FROM active_chats;")
    
    logging.info("Старые сессии поиска и чатов очищены.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logging.info("Бот запускается...")
    # Этот вызов блокирующий и сам обрабатывает сигналы остановки (SIGINT, SIGTERM)
    await app.run_polling()

# ИЗМЕНЕНИЕ ЗДЕСЬ: Мы убрали try/except и просто вызываем asyncio.run(main())
if __name__ == "__main__":
    asyncio.run(main())
