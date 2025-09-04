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

import database
import keyboards

# ... (Логирование, переменные, константы остаются без изменений) ...
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ADMIN_IDS = set()

if not BOT_TOKEN or not ADMIN_PASSWORD:
    logging.error("BOT_TOKEN или ADMIN_PASSWORD не установлены!")
    exit(1)

REWARD_FOR_REFERRAL = 10
COST_FOR_18PLUS = 50
COST_FOR_UNBAN = 100
COST_FOR_PHOTO = 50
MAX_WARNINGS = 3

# --- УБИРАЕМ ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ДЛЯ СОСТОЯНИЯ ---
# waiting_users -> заменено на таблицу search_queue
# active_chats -> заменено на таблицу active_chats
# show_name_requests -> будет храниться в context.bot_data для простоты, т.к. это менее критичные данные
# active_tasks -> по-прежнему будет в памяти, т.к. задачи нельзя сохранить в БД
active_tasks = {}
# user_interests -> заменено на таблицу search_queue

available_interests = {
    "Музыка": "🎵", "Игры": "🎮", "Кино": "🎬",
    "Путешествия": "✈️", "Общение": "💬", "18+": "🔞"
}
# ====== ОБРАБОТЧИКИ КОМАНД ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    user = update.effective_user
    await database.ensure_user(user.id, user.username)

    # Реферальная система (немного улучшена)
    if context.args and context.args[0].isdigit():
        referrer_id = int(context.args[0])
        if referrer_id != user.id:
            await database.ensure_user(referrer_id) 
            if await database.add_referral(referrer_id, user.id):
                await database.update_balance(referrer_id, REWARD_FOR_REFERRAL)
                try:
                    await context.bot.send_message(
                        referrer_id,
                        f"🎉 Новый пользователь @{user.username} по вашей ссылке! Вам начислено {REWARD_FOR_REFERRAL} валюты."
                    )
                except Exception:
                    # Если бот заблокирован у пригласившего, ничего страшного
                    pass

    await update.message.reply_text(
        "👋 Добро пожаловать в анонимный чат!\n\n"
        "⚠️ Перед началом подтвердите согласие с правилами:\n"
        "• Запрещено нарушать законы.\n"
        "• Соблюдайте уважение.\n\n"
        "Нажмите 'Согласен' чтобы начать.",
        reply_markup=keyboards.get_agreement_keyboard()
    )


# ... (admin_command остается без изменений) ...

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

async def show_interests_menu(update: Update, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню выбора интересов."""
    if await database.is_user_banned(user_id):
        await update.message.reply_text("❌ Вы заблокированы и не можете искать собеседников.")
        return
    # Проверяем, не в чате ли пользователь
    if await database.get_partner_id(user_id):
        await update.message.reply_text("❌ Вы уже в чате. Завершите его, чтобы начать новый.")
        return
    
    # Временно храним выбор интересов в user_data, пока пользователь не нажал "Готово"
    context.user_data['selected_interests'] = []
    await update.message.reply_text(
        "Выберите интересы, чтобы найти подходящего собеседника:",
        reply_markup=await keyboards.get_interests_keyboard(user_id, {user_id: []}, available_interests)
    )

# ... (show_admin_menu без изменений) ...

# ====== ЛОГИКА ЧАТА (ПЕРЕРАБОТАНА) ======

async def start_search_logic(user_id: int, interests: list, context: ContextTypes.DEFAULT_TYPE):
    """Основная логика поиска собеседника."""
    # Ищем партнера сразу
    partner_id = await database.find_partner_in_queue(user_id, interests)
    
    if partner_id:
        # Партнер найден!
        await database.remove_from_search_queue(partner_id) # Удаляем его из очереди
        await start_chat(context, user_id, partner_id)
    else:
        # Партнер не найден, добавляем себя в очередь
        await database.add_to_search_queue(user_id, interests)
        await context.bot.send_message(user_id, "⏳ Ищем собеседника с похожими интересами...")

async def start_chat(context: ContextTypes.DEFAULT_TYPE, u1: int, u2: int):
    """Начинает чат между двумя пользователями (теперь через БД)."""
    await database.create_chat(u1, u2)
    
    markup = keyboards.get_chat_keyboard()
    msg = "🎉 Собеседник найден! Начинайте общение."
    # Можно добавить таймер, если нужно, логика та же
    await context.bot.send_message(u1, msg, reply_markup=markup)
    await context.bot.send_message(u2, msg, reply_markup=markup)

async def end_chat(user_id: int, context: ContextTypes.DEFAULT_TYPE, initiator_message: str, partner_message: str):
    """Завершает чат для двух пользователей (улучшенная версия)."""
    chat_pair = await database.delete_chat(user_id)
    if chat_pair:
        u1, u2 = chat_pair
        
        # Определяем, кто есть кто
        initiator_id = user_id
        partner_id = u2 if u1 == user_id else u1

        await context.bot.send_message(initiator_id, initiator_message, reply_markup=ReplyKeyboardRemove())
        await context.bot.send_message(partner_id, partner_message, reply_markup=ReplyKeyboardRemove())
        
        # Возвращаем обоим главное меню
        await show_main_menu(initiator_id, context)
        await show_main_menu(partner_id, context)

# ====== ОБРАБОТЧИК КНОПОК (CALLBACK) ======
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик всех inline-кнопок."""
    query = update.callback_query
    user = query.from_user
    await database.ensure_user(user.id, user.username)
    await query.answer()
    data = query.data
    
    # ... (кнопки agree и unban_request без изменений) ...

    # --- Выбор интересов (обновленная логика) ---
    elif data.startswith("interest_"):
        interest_key = data.replace("interest_", "")
        selected = context.user_data.get('selected_interests', [])
        
        if interest_key in selected:
            selected.remove(interest_key)
        else:
            selected.append(interest_key)
        context.user_data['selected_interests'] = selected

        # get_interests_keyboard ожидает dict, создаем его
        temp_user_interests = {user.id: selected}
        
        await query.edit_message_reply_markup(
            reply_markup=await keyboards.get_interests_keyboard(user.id, temp_user_interests, available_interests)
        )

    elif data == "interests_done":
        selected = context.user_data.get('selected_interests', [])
        if not selected:
            await query.answer("❌ Пожалуйста, выберите хотя бы один интерес.", show_alert=True)
            return
        
        # Проверка на 18+
        if "18+" in selected and not await database.has_unlocked_18plus(user.id):
            balance = await database.get_balance(user.id)
            if balance >= COST_FOR_18PLUS:
                await database.update_balance(user.id, -COST_FOR_18PLUS)
                await database.unlock_18plus(user.id)
                await query.edit_message_text(f"✅ Чат 18+ разблокирован за {COST_FOR_18PLUS} валюты!")
            else:
                await query.answer(f"❌ Недостаточно валюты для 18+ (нужно {COST_FOR_18PLUS}).", show_alert=True)
                # Удаляем 18+ и не начинаем поиск, чтобы пользователь мог исправить
                context.user_data['selected_interests'].remove("18+")
                return
        
        await query.edit_message_text(f"✅ Интересы выбраны: {', '.join(selected)}. Начинаем поиск...")
        # Запускаем логику поиска
        await start_search_logic(user.id, selected, context)
        # Очищаем временные данные
        context.user_data.pop('selected_interests', None)

    # ... (остальные обработчики кнопок без изменений)

# ====== ОБРАБОТЧИК СООБЩЕНИЙ ======
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовые сообщения."""
    user = update.effective_user
    await database.ensure_user(user.id, user.username)
    text = update.message.text

    if await database.is_user_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы.")
        return
        
    # ... (Логика админ-ввода без изменений) ...
    
    # --- Команды из меню ---
    if text == "🔍 Поиск собеседника":
        await show_interests_menu(update, user.id, context)
    # ... (баланс, рефералы без изменений) ...

    # --- Логика в чате (обновлена) ---
    else:
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
        # Если пользователь не в чате и сообщение не команда - можно проигнорировать или подсказать
        else:
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
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
