import asyncio
import logging
import os
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
import database
import keyboards

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = {int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',') if admin_id.strip()}

if not BOT_TOKEN:
    logging.error("BOT_TOKEN не установлен!")
    exit(1)

REWARD_FOR_REFERRAL = 10
COST_FOR_UNBAN = 100
available_interests = {"Музыка": "🎵", "Игры": "🎮", "Кино": "🎬", "Путешествия": "✈️", "Общение": "💬"}

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
                    await context.bot.send_message(referrer_id, f"🎉 Вам начислено {REWARD_FOR_REFERRAL} за нового пользователя!")
                except Exception as e:
                    logging.warning(f"Не удалось уведомить реферера {referrer_id}: {e}")
    await update.message.reply_text("👋 Добро пожаловать! Нажмите 'Согласен', чтобы подтвердить согласие с правилами.", reply_markup=keyboards.get_agreement_keyboard())

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in ADMIN_IDS:
        context.user_data['is_admin_mode'] = True
        await update.message.reply_text("🔐 Вы вошли в режим администратора.", reply_markup=keyboards.get_admin_reply_keyboard())
    elif ADMIN_PASSWORD:
        context.user_data['awaiting_admin_password'] = True
        await update.message.reply_text("🔐 Введите пароль администратора:")
    else:
        await update.message.reply_text("❌ У вас нет доступа.")

async def show_main_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    if await database.is_user_banned(chat_id):
        await context.bot.send_message(chat_id, "❌ Вы заблокированы.", reply_markup=keyboards.get_unban_keyboard(COST_FOR_UNBAN))
    else:
        await context.bot.send_message(chat_id, "⬇️ Выберите действие из меню:", reply_markup=keyboards.get_main_menu_keyboard())

async def start_search_logic(user_id: int, interests: list, context: ContextTypes.DEFAULT_TYPE):
    partner_id = await database.find_partner_in_queue(user_id, interests)
    if partner_id:
        await start_chat(context, user_id, partner_id)
    else:
        await database.add_to_search_queue(user_id, interests)
        await context.bot.send_message(user_id, "⏳ Ищем собеседника с похожими интересами...")

async def start_chat(context: ContextTypes.DEFAULT_TYPE, u1: int, u2: int):
    markup = keyboards.get_chat_keyboard()
    msg = "🎉 Собеседник найден! Начинайте общение."
    await database.create_chat(u1, u2)
    await context.bot.send_message(u1, msg, reply_markup=markup)
    await context.bot.send_message(u2, msg, reply_markup=markup)

async def end_chat(user_id: int, context: ContextTypes.DEFAULT_TYPE, initiator_msg: str, partner_msg: str):
    chat_pair = await database.delete_chat(user_id)
    if chat_pair:
        partner_id = chat_pair[1] if chat_pair[0] == user_id else chat_pair[0]
        await context.bot.send_message(user_id, initiator_msg, reply_markup=ReplyKeyboardRemove())
        await show_main_menu(user_id, context)
        await context.bot.send_message(partner_id, partner_msg, reply_markup=ReplyKeyboardRemove())
        await show_main_menu(partner_id, context)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    await database.ensure_user(user.id, user.username)
    data = query.data

    if data == "agree":
        await query.message.delete()
        await show_main_menu(user.id, context)

    elif data == "unban_request":
        if await database.get_balance(user.id) >= COST_FOR_UNBAN:
            await database.update_balance(user.id, -COST_FOR_UNBAN)
            await database.unban_user(user.id)
            await query.edit_message_text("✅ Вы успешно разблокированы!")
            await show_main_menu(user.id, context)
        else:
            await query.edit_message_text(f"❌ Недостаточно валюты. Необходимо {COST_FOR_UNBAN}.")

    elif data.startswith("interest_"):
        interest = data.split("_", 1)[1]
        selected = context.user_data.setdefault('selected_interests', [])
        if interest in selected: selected.remove(interest)
        else: selected.append(interest)
        await query.edit_message_reply_markup(reply_markup=keyboards.get_interests_keyboard(selected, available_interests))

    elif data == "interests_done":
        selected = context.user_data.get('selected_interests', [])
        if not selected:
            return await query.answer("❌ Пожалуйста, выберите хотя бы один интерес.", show_alert=True)
        await query.edit_message_text("✅ Интересы выбраны. Начинаем поиск...")
        await start_search_logic(user.id, selected, context)

    elif data == "admin_confirm_stop_all":
        if user.id not in ADMIN_IDS: return
        user_ids = await database.get_all_active_chat_users()
        await database.clear_all_active_chats()
        await query.edit_message_text(f"✅ Все {len(user_ids)//2} чаты принудительно завершены.")
        for uid in user_ids:
            try:
                await context.bot.send_message(uid, "🚫 Ваш чат был завершен администратором.", reply_markup=ReplyKeyboardRemove())
                await show_main_menu(uid, context)
            except Exception as e:
                logging.warning(f"Не удалось уведомить {uid}: {e}")

    elif data == "admin_cancel_stop_all":
        if user.id not in ADMIN_IDS: return
        await query.edit_message_text("❌ Действие отменено.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    await database.ensure_user(user.id, user.username)

    if await database.is_user_banned(user.id): return

    if context.user_data.get("awaiting_admin_password"):
        if text == ADMIN_PASSWORD:
            ADMIN_IDS.add(user.id)
            context.user_data['is_admin_mode'] = True
            await update.message.reply_text("✅ Пароль верный.", reply_markup=keyboards.get_admin_reply_keyboard())
        else:
            await update.message.reply_text("❌ Неверный пароль.")
        context.user_data.pop("awaiting_admin_password")
        return

    # --- АДМИН-РЕЖИМ ---
    if context.user_data.get('is_admin_mode'):
        # ... Логика для админ-команд ...
        if text == "⬅️ Выйти из админ-режима":
            context.user_data.pop('is_admin_mode')
            await update.message.reply_text("Вы вышли из режима администратора.", reply_markup=keyboards.get_main_menu_keyboard())
        # ... и так далее
        # Тут нужно дописать логику для команд "Забанить", "Разбанить" и т.д.,
        # которая будет устанавливать флаги (например, awaiting_ban_id) и обрабатывать следующий ввод.
        return

    # --- ОБЫЧНЫЙ РЕЖИМ ---
    partner_id = await database.get_partner_id(user.id)
    if partner_id:
        if text == "🚫 Завершить чат":
            await end_chat(user.id, context, "❌ Вы завершили чат.", "❌ Собеседник вышел.")
        elif text == "🔍 Начать новый чат":
            await end_chat(user.id, context, "❌ Чат завершен. Ищем новый...", "❌ Собеседник решил найти новый чат.")
            await update.message.reply_text("Выберите интересы:", reply_markup=keyboards.get_interests_keyboard([], available_interests))
        else:
            await context.bot.send_message(partner_id, text)
        return

    if text == "🔍 Поиск собеседника":
        if await database.get_partner_id(user.id):
            return await update.message.reply_text("❌ Вы уже в чате.")
        context.user_data['selected_interests'] = []
        await update.message.reply_text("Выберите ваши интересы:", reply_markup=keyboards.get_interests_keyboard([], available_interests))
    
    elif text == "💰 Мой баланс":
        balance = await database.get_balance(user.id)
        await update.message.reply_text(f"💰 Ваш баланс: {balance}")

    elif text == "🔗 Мои рефералы":
        count = await database.get_referral_count(user.id)
        bot_username = (await context.bot.get_me()).username
        await update.message.reply_text(f"Приглашено: {count}\nВаша ссылка: `https://t.me/{bot_username}?start={user.id}`", parse_mode="MarkdownV2")

async def main() -> None:
    try:
        await database.init_db()
    except Exception as e:
        logging.critical(f"Не удалось подключиться к БД: {e}")
        return
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    async with app:
        logging.info("Бот запускается...")
        await app.start()
        await app.updater.start_polling()
        logging.info("Бот успешно запущен.")
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
