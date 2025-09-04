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
from telegram.error import Forbidden

import database
import keyboards

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

if not BOT_TOKEN or not ADMIN_PASSWORD:
    logging.error("BOT_TOKEN или ADMIN_PASSWORD не установлены!")
    exit(1)

# --- Обработчики команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await database.ensure_user(user.id, user.username)
    # ... (код реферальной системы остается без изменений) ...
    await update.message.reply_text(
        "👋 Добро пожаловать в анонимный чат!",
        reply_markup=keyboards.get_agreement_keyboard()
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await database.is_admin(user_id):
        await update.message.reply_text("👑 Админ-панель", reply_markup=keyboards.get_admin_keyboard())
    else:
        await update.message.reply_text("🔐 Введите пароль:")
        context.user_data['awaiting_admin_password'] = True

# --- Основные функции и меню ---
async def show_main_menu(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    if await database.is_user_banned(user_id):
        # ... (код для забаненных) ...
        return

    is_admin = await database.is_admin(user_id)
    await context.bot.send_message(
        user_id, "Выберите действие:",
        reply_markup=keyboards.get_main_menu_keyboard(is_admin)
    )

# --- Логика чата (полностью переписана) ---
async def find_partner(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(user_id, "⏳ Ищем собеседника...")
    partner_id = await database.find_waiting_partner(user_id)

    if partner_id:
        await database.create_chat(user_id, partner_id)
        await start_chat_messaging(user_id, partner_id, context)
    else:
        await database.set_user_status(user_id, 'waiting')

async def start_chat_messaging(u1: int, u2: int, context: ContextTypes.DEFAULT_TYPE):
    markup = keyboards.get_chat_keyboard()
    msg = "🎉 Собеседник найден! Можете начинать общение."
    try:
        await context.bot.send_message(u1, msg, reply_markup=markup)
        await context.bot.send_message(u2, msg, reply_markup=markup)
    except Forbidden:
        logging.warning(f"Не удалось отправить сообщение одному из пользователей: {u1} или {u2}")
        # Если не можем написать одному, завершаем чат для другого
        await end_chat(u1, context)

async def end_chat(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    partner_id = await database.delete_chat(user_id)
    
    await context.bot.send_message(user_id, "❌ Чат завершён.", reply_markup=ReplyKeyboardRemove())
    await show_main_menu(user_id, context)

    if partner_id:
        try:
            await context.bot.send_message(partner_id, "❌ Собеседник завершил чат.", reply_markup=ReplyKeyboardRemove())
            await show_main_menu(partner_id, context)
        except Forbidden:
            logging.warning(f"Не удалось уведомить партнера {partner_id} о завершении чата.")

# --- Обработчик кнопок ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    data = query.data

    if data == "agree":
        await query.message.delete()
        await show_main_menu(user.id, context)
        return

    # --- Админ-панель ---
    if data == "admin_exit":
        await query.message.delete()
    elif data == "admin_ban":
        await query.message.reply_text("Введите ID пользователя для бана:")
        context.user_data['awaiting_ban_id'] = True
    elif data == "admin_unban":
        await query.message.reply_text("Введите ID пользователя для разбана:")
        context.user_data['awaiting_unban_id'] = True
    elif data == "admin_add_currency":
        await query.message.reply_text("Введите ID пользователя и сумму через пробел (например, 12345 100):")
        context.user_data['awaiting_add_currency'] = True

# --- Обработчик сообщений ---
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    await database.ensure_user(user.id, user.username)

    if await database.is_user_banned(user.id):
        await update.message.reply_text("❌ Вы заблокированы.")
        return

    # --- Обработка ввода для админ-действий ---
    if context.user_data.get('awaiting_admin_password'):
        if text == ADMIN_PASSWORD:
            await database.set_admin(user.id)
            await update.message.reply_text("✅ Пароль верный. Доступ предоставлен. Кнопка админ-панели добавлена в меню.")
            await show_main_menu(user.id, context)
        else:
            await update.message.reply_text("❌ Неверный пароль.")
        del context.user_data['awaiting_admin_password']
        return

    if context.user_data.get('awaiting_ban_id'):
        try:
            target_id = int(text)
            await database.ban_user(target_id)
            await update.message.reply_text(f"✅ Пользователь {target_id} забанен.")
        except ValueError:
            await update.message.reply_text("❌ Неверный ID.")
        del context.user_data['awaiting_ban_id']
        return

    if context.user_data.get('awaiting_unban_id'):
        try:
            target_id = int(text)
            await database.unban_user(target_id)
            await update.message.reply_text(f"✅ Пользователь {target_id} разбанен.")
        except ValueError:
            await update.message.reply_text("❌ Неверный ID.")
        del context.user_data['awaiting_unban_id']
        return
        
    if context.user_data.get('awaiting_add_currency'):
        try:
            target_id, amount = map(int, text.split())
            await database.update_balance(target_id, amount)
            await update.message.reply_text(f"✅ Пользователю {target_id} начислено {amount} валюты.")
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Неверный формат. Введите ID и сумму через пробел.")
        del context.user_data['awaiting_add_currency']
        return

    # --- Основное меню и логика чата ---
    user_status = await database.get_user_status(user.id)

    if user_status == 'in_chat':
        if text == "🚫 Завершить чат" or text == "🔍 Начать новый чат":
            await end_chat(user.id, context)
            if text == "🔍 Начать новый чат":
                await find_partner(user.id, context)
        else:
            partner_id = await database.get_partner_id(user.id)
            if partner_id:
                try:
                    await context.bot.send_message(partner_id, text)
                except Forbidden:
                    await update.message.reply_text("⚠️ Не удалось доставить сообщение. Возможно, собеседник заблокировал бота. Чат завершен.")
                    await end_chat(user.id, context)
    else: # Статус 'idle' или 'waiting'
        if text == "🔍 Поиск собеседника":
            await find_partner(user.id, context)
        elif text == "💰 Мой баланс":
            balance = await database.get_balance(user.id)
            await update.message.reply_text(f"💰 Ваш текущий баланс: {balance}")
        elif text == "🔗 Мои рефералы":
            # ... (код для рефералов) ...
            pass
        elif text == "👑 Админ-панель" and await database.is_admin(user.id):
            await admin_command(update, context)

# --- Запуск бота ---
async def main():
    await database.init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logging.info("Бот запускается...")
    async with app:
        await app.initialize()
        await app.updater.start_polling()
        await app.start()
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())

