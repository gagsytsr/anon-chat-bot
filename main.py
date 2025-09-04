# main.py

import asyncio
import logging
import os
import re
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
import database
import keyboards

# ... (НАСТРОЙКИ и КОНСТАНТЫ без изменений) ...
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = {int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',') if admin_id.strip()}
if not BOT_TOKEN:
    logging.error("BOT_TOKEN не установлен! Бот не может быть запущен.")
    exit(1)
REWARD_FOR_REFERRAL = 10
COST_FOR_18PLUS = 50
COST_FOR_UNBAN = 100
MAX_WARNINGS = 3
available_interests = {
    "Музыка": "🎵", "Игры": "🎮", "Кино": "🎬",
    "Путешествия": "✈️", "Общение": "💬", "18+": "🔞"
}

# ... (функции start, show_main_menu, show_interests_menu и т.д. без изменений до admin_command) ...
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await database.ensure_user(user.id, user.username)
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
    await update.message.reply_text(
        "👋 Добро пожаловать в анонимный чат!\n\n"
        "⚠️ Перед началом подтвердите согласие с правилами:\n"
        "• Запрещено нарушать законы.\n"
        "• Соблюдайте уважение.\n\n"
        "Нажмите 'Согласен' чтобы начать.",
        reply_markup=keyboards.get_agreement_keyboard()
    )
async def show_main_menu(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    if await database.is_user_banned(user_id):
        await context.bot.send_message(
            user_id, "❌ Вы заблокированы.",
            reply_markup=keyboards.get_unban_keyboard(COST_FOR_UNBAN)
        )
    else:
        await context.bot.send_message(
            user_id, "⬇️ Выберите действие из меню:",
            reply_markup=keyboards.get_main_menu_keyboard()
        )
async def show_interests_menu(update: Update, user_id: int, context: ContextTypes.DEFAULT_TYPE):
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
async def start_search_logic(user_id: int, interests: list, context: ContextTypes.DEFAULT_TYPE):
    partner_id = await database.find_partner_in_queue(user_id, interests)
    if partner_id:
        await database.remove_from_search_queue(partner_id)
        await start_chat(context, user_id, partner_id)
    else:
        await database.add_to_search_queue(user_id, interests)
        await context.bot.send_message(user_id, "⏳ Ищем собеседника с похожими интересами...")
async def start_chat(context: ContextTypes.DEFAULT_TYPE, u1: int, u2: int):
    await database.create_chat(u1, u2)
    markup = keyboards.get_chat_keyboard()
    msg = "🎉 Собеседник найден! Начинайте общение."
    await context.bot.send_message(u1, msg, reply_markup=markup)
    await context.bot.send_message(u2, msg, reply_markup=markup)
async def end_chat(user_id: int, context: ContextTypes.DEFAULT_TYPE, initiator_message: str, partner_message: str):
    chat_pair = await database.delete_chat(user_id)
    if chat_pair:
        u1, u2 = chat_pair
        initiator_id = user_id
        partner_id = u2 if u1 == user_id else u1
        await context.bot.send_message(initiator_id, initiator_message, reply_markup=ReplyKeyboardRemove())
        await show_main_menu(initiator_id, context)
        await context.bot.send_message(partner_id, partner_message, reply_markup=ReplyKeyboardRemove())
        await show_main_menu(partner_id, context)

# ОБНОВЛЕННАЯ КОМАНДА /admin
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вход в режим администратора."""
    user = update.effective_user
    if user.id in ADMIN_IDS:
        context.user_data['is_admin_mode'] = True
        await update.message.reply_text(
            "🔐 Вы вошли в режим администратора.",
            reply_markup=keyboards.get_admin_reply_keyboard()
        )
    elif ADMIN_PASSWORD:
        await update.message.reply_text("🔐 Введите пароль администратора:")
        context.user_data["awaiting_admin_password"] = True
    else:
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")

# ОБНОВЛЕННЫЙ ОБРАБОТЧИК КНОПОК
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await database.ensure_user(user.id, user.username)
    await query.answer()
    data = query.data

    if data == "agree":
        await query.message.delete()
        await show_main_menu(user.id, context)

    elif data == "unban_request":
        # ... (логика без изменений) ...
        pass

    elif data.startswith("interest_") or data == "interests_done":
        # ... (логика без изменений) ...
        pass
    
    # НОВАЯ ЛОГИКА для подтверждения остановки чатов
    elif data == "admin_confirm_stop_all":
        if user.id not in ADMIN_IDS: return
        
        chat_user_ids = await database.get_all_active_chat_users()
        await database.clear_all_active_chats()
        
        stopped_count = len(chat_user_ids) // 2
        await query.edit_message_text(f"✅ Все {stopped_count} чаты принудительно завершены.")

        for user_id in chat_user_ids:
            try:
                await context.bot.send_message(
                    user_id,
                    "🚫 Ваш чат был принудительно завершен администратором.",
                    reply_markup=ReplyKeyboardRemove()
                )
                await show_main_menu(user_id, context)
            except Exception as e:
                logging.warning(f"Не удалось уведомить пользователя {user_id} о завершении чата: {e}")
    
    elif data == "admin_cancel_stop_all":
        if user.id not in ADMIN_IDS: return
        await query.edit_message_text("❌ Действие отменено.")


# ОБНОВЛЕННЫЙ ОБРАБОТЧИК СООБЩЕНИЙ
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    await database.ensure_user(user.id, user.username)

    if await database.is_user_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы.")
        return

    # --- ЛОГИКА ВХОДА В АДМИНКУ ПО ПАРОЛЮ ---
    if context.user_data.get("awaiting_admin_password"):
        if text == ADMIN_PASSWORD:
            ADMIN_IDS.add(user.id)
            context.user_data['is_admin_mode'] = True
            await update.message.reply_text(
                "✅ Пароль верный. Вы вошли в режим администратора.",
                reply_markup=keyboards.get_admin_reply_keyboard()
            )
        else:
            await update.message.reply_text("❌ Неверный пароль.")
        context.user_data.pop("awaiting_admin_password")
        return

    # --- ОБРАБОТКА КОМАНД ИЗ АДМИН-КЛАВИАТУРЫ ---
    if context.user_data.get('is_admin_mode'):
        # Выход из режима админа
        if text == "⬅️ Выйти из админ-режима":
            context.user_data.pop('is_admin_mode')
            await update.message.reply_text(
                "Вы вышли из режима администратора.",
                reply_markup=keyboards.get_main_menu_keyboard()
            )
            return

        # Запрос на ввод данных
        if text == "👮‍♂️ Забанить":
            await update.message.reply_text("Введите ID пользователя для БАНА:")
            context.user_data["awaiting_ban_id"] = True
            return
        if text == "🔓 Разбанить":
            await update.message.reply_text("Введите ID пользователя для РАЗБАНА:")
            context.user_data["awaiting_unban_id"] = True
            return
        if text == "💰 Выдать валюту":
            await update.message.reply_text("ID и сумма через пробел (напр. `12345 100`):", parse_mode="MarkdownV2")
            context.user_data["awaiting_add_currency"] = True
            return
        if text == "💸 Забрать валюту":
            await update.message.reply_text("ID и сумма для списания (напр. `12345 50`):", parse_mode="MarkdownV2")
            context.user_data["awaiting_remove_currency"] = True
            return

        # Выполнение действий
        if text == "📊 Статистика":
            stats = await database.get_bot_statistics()
            await update.message.reply_text(
                f"📊 **Статистика Бота**\n\n"
                f"👥 Всего пользователей: *{stats['total_users']}*\n"
                f"🚫 Забанено: *{stats['banned_users']}*\n"
                f"💬 В чатах сейчас: *{stats['users_in_chats']}*\n"
                f"⏳ В поиске сейчас: *{stats['users_in_queue']}*",
                parse_mode="MarkdownV2"
            )
            return
        if text == "🚫 Завершить все чаты":
            await update.message.reply_text(
                "⚠️ Вы уверены, что хотите принудительно завершить ВСЕ активные чаты?",
                reply_markup=keyboards.get_stop_all_confirmation_keyboard()
            )
            return
        
        # Обработка ввода данных после запроса
        if context.user_data.get("awaiting_ban_id"):
            # ... (логика бана)
            pass
        if context.user_data.get("awaiting_unban_id"):
            # ... (логика разбана)
            pass
        if context.user_data.get("awaiting_add_currency"):
            # ... (логика добавления валюты)
            pass
        if context.user_data.get("awaiting_remove_currency"):
            try:
                target_id_str, amount_str = text.split()
                target_id = int(target_id_str)
                amount = -abs(int(amount_str)) # Убедимся, что число отрицательное
                await database.update_balance(target_id, amount)
                await update.message.reply_text(f"✅ У пользователя {target_id} списано {-amount} валюты.")
                await context.bot.send_message(target_id, f"💸 Администратор списал с вас {-amount} валюты.")
            except (ValueError, IndexError):
                await update.message.reply_text("❌ Неверный формат. Введите ID и сумму через пробел.")
            finally:
                context.user_data.pop("awaiting_remove_currency")
            return

    # --- ЛОГИКА ДЛЯ ОБЫЧНЫХ ПОЛЬЗОВАТЕЛЕЙ ---
    # ... (весь оставшийся код message_handler без изменений)
    pass


# ====== ЗАПУСК БОТА ======
async def main() -> None:
    # ... (код без изменений)
    pass

if __name__ == "__main__":
    asyncio.run(main())
