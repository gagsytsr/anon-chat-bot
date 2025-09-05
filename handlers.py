# handlers.py
import asyncio
import logging
import re

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes

# Импортируем наши модули
import database as db
import keyboards as kb
from config import (
    ADMIN_PASSWORD, ADMIN_IDS, REWARD_FOR_REFERRAL, COST_FOR_18PLUS,
    COST_FOR_UNBAN, COST_FOR_PHOTO, MAX_WARNINGS
)

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Вспомогательные функции ---

async def show_main_menu(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет главное меню пользователю."""
    user = await db.get_or_create_user(user_id)
    if user['is_banned']:
        await context.bot.send_message(
            user_id,
            "❌ Вы заблокированы. Чтобы получить доступ к боту, вы должны разблокировать себя.",
            reply_markup=kb.get_ban_keyboard()
        )
    else:
        await context.bot.send_message(
            user_id,
            "Выберите действие:",
            reply_markup=kb.get_main_menu_keyboard()
        )

async def end_chat_session(user_id: int, context: ContextTypes.DEFAULT_TYPE, message: str):
    """Универсальная функция для завершения чата."""
    partner_id = await db.end_chat(user_id)
    
    pair_key = tuple(sorted((user_id, partner_id)))
    context.bot_data.pop(pair_key, None) # Удаляем историю и запросы

    if partner_id:
        await context.bot.send_message(partner_id, f"❌ {message}", reply_markup=ReplyKeyboardRemove())
        await show_main_menu(partner_id, context)
    
    await context.bot.send_message(user_id, "❌ Чат завершён.", reply_markup=ReplyKeyboardRemove())
    await show_main_menu(user_id, context)


# --- Обработчики команд ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    user_id = update.effective_user.id
    user = await db.get_or_create_user(user_id)

    # Реферальная система
    if context.args and not user['invited_by']:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user_id:
                await db.add_referral(user_id, referrer_id, REWARD_FOR_REFERRAL)
                await context.bot.send_message(
                    referrer_id,
                    f"🎉 Новый пользователь по вашей ссылке! Вам начислено {REWARD_FOR_REFERRAL} валюты."
                )
        except (ValueError, IndexError):
            logger.warning(f"Invalid referrer ID in start command: {context.args}")
            
    # Соглашение с правилами
    await db.set_agreement(user_id, False)
    keyboard = [[InlineKeyboardButton("✅ Согласен", callback_data="agree")]]
    await update.message.reply_text(
        "👋 Добро пожаловать в анонимный чат!\n\n"
        "⚠️ Перед началом подтвердите согласие с правилами:\n"
        "• Запрещено нарушать законы.\n"
        "• Соблюдайте уважение.\n\n"
        "Нажмите 'Согласен' чтобы начать.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /admin."""
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        await update.message.reply_text("🔐 Админ-панель", reply_markup=kb.get_admin_keyboard())
    else:
        await update.message.reply_text("🔐 Введите пароль:")
        context.user_data["awaiting_admin_password"] = True


# --- Обработчик кнопок (Callback) ---

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик всех inline-кнопок."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    user = await db.get_or_create_user(user_id)

    if data == "agree":
        await db.set_agreement(user_id, True)
        await query.message.delete()
        await show_main_menu(user_id, context)

    elif data == "unban_request":
        if user['balance'] >= COST_FOR_UNBAN:
            await db.update_balance(user_id, -COST_FOR_UNBAN)
            await db.set_ban_status(user_id, False)
            new_balance = user['balance'] - COST_FOR_UNBAN
            await query.edit_message_text(f"✅ Вы успешно разблокированы за {COST_FOR_UNBAN} валюты. Ваш текущий баланс: {new_balance}. Счётчик предупреждений сброшен.")
            await show_main_menu(user_id, context)
        else:
            await query.edit_message_text(f"❌ Недостаточно валюты для разблокировки. Необходимо {COST_FOR_UNBAN}. Ваш баланс: {user['balance']}.")

    elif data.startswith("interest_"):
        interest_key = data.replace("interest_", "")
        current_interests = context.user_data.get("interests", [])
        if interest_key in current_interests:
            current_interests.remove(interest_key)
        else:
            current_interests.append(interest_key)
        context.user_data["interests"] = current_interests
        await query.edit_message_reply_markup(reply_markup=await kb.get_interests_keyboard(current_interests))

    elif data == "interests_done":
        selected_interests = context.user_data.get("interests", [])
        if not selected_interests:
            await query.edit_message_text("❌ Пожалуйста, выберите хотя бы один интерес.", reply_markup=await kb.get_interests_keyboard())
            return

        if "18+" in selected_interests and not user['unlocked_18plus']:
            if user['balance'] >= COST_FOR_18PLUS:
                await db.update_balance(user_id, -COST_FOR_18PLUS)
                await db.unlock_18plus(user_id)
            else:
                await query.edit_message_text(f"❌ Недостаточно валюты для разблокировки чата 18+ (необходимо {COST_FOR_18PLUS}). Ваш баланс: {user['balance']}.")
                return

        await db.update_user_interests(user_id, selected_interests)
        await db.update_user_status(user_id, 'waiting')
        await query.edit_message_text(f"✅ Ваши интересы: {', '.join(selected_interests)}. Ищем собеседника...")

        partner_id = await db.find_partner(user_id, selected_interests)
        if partner_id:
            await db.create_chat(user_id, partner_id)
            await context.bot.send_message(user_id, "🎉 Собеседник найден!", reply_markup=kb.get_chat_keyboard())
            await context.bot.send_message(partner_id, "🎉 Собеседник найден!", reply_markup=kb.get_chat_keyboard())
        else:
            await context.bot.send_message(user_id, "⏳ Пока никого нет, мы сообщим, как только кто-то найдется.")

    # ... (обработчики других кнопок, таких как admin, report и т.д., добавляются аналогично) ...


# --- Обработчик сообщений ---

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовые сообщения."""
    user_id = update.effective_user.id
    text = update.message.text
    user = await db.get_or_create_user(user_id)

    # --- Админ-логика ---
    if context.user_data.get("awaiting_admin_password"):
        if text.strip() == ADMIN_PASSWORD:
            ADMIN_IDS.add(user_id)
            await update.message.reply_text("✅ Пароль верный!", reply_markup=ReplyKeyboardRemove())
            await admin_command(update, context)
        else:
            await update.message.reply_text("❌ Неверный пароль.")
        context.user_data.pop("awaiting_admin_password", None)
        return
    # ... (другие админские инпуты: ban_id, add_currency и т.д.) ...
    
    if user['is_banned']:
        await show_main_menu(user_id, context)
        return

    # --- Логика в чате ---
    if user['status'] == 'in_chat':
        partner_id = user['partner_id']
        partner = await db.get_or_create_user(partner_id)

        if partner['is_banned']:
            await end_chat_session(user_id, context, "Ваш собеседник был забанен.")
            return
            
        if text == "🚫 Завершить чат":
            await end_chat_session(user_id, context, "Собеседник завершил чат.")
        elif text == "🔍 Начать новый чат":
            await end_chat_session(user_id, context, "Собеседник решил начать новый чат.")
            # Сразу инициируем новый поиск
            await update.message.reply_text("Выберите интересы для нового поиска:", reply_markup=await kb.get_interests_keyboard())
        else:
            # Пересылка сообщения
            await context.bot.send_message(partner_id, text)

    # --- Логика в меню ---
    elif user['status'] == 'idle' or user['status'] == 'waiting':
        if text == "🔍 Поиск собеседника":
            if user['status'] == 'in_chat':
                await update.message.reply_text("❌ Вы уже в чате.")
                return
            context.user_data["interests"] = []
            await update.message.reply_text("Выберите интересы:", reply_markup=await kb.get_interests_keyboard())
        
        elif text == "💰 Мой баланс":
            await update.message.reply_text(f"💰 Ваш текущий баланс: {user['balance']}")
        
        elif text == "🔗 Мои рефералы":
            link = f"https://t.me/{context.bot.username}?start={user_id}"
            await update.message.reply_text(f"🔗 Ваша ссылка: {link}\n👥 Приглашено: {user['referrals_count']}")
        
        else:
            await show_main_menu(user_id, context)


async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает медиа сообщения (фото, видео, и т.д.)."""
    user_id = update.effective_user.id
    user = await db.get_or_create_user(user_id)

    if user['is_banned'] or user['status'] != 'in_chat':
        return

    partner_id = user['partner_id']
    
    if update.message.photo:
        if user['balance'] >= COST_FOR_PHOTO:
            await db.update_balance(user_id, -COST_FOR_PHOTO)
            await context.bot.send_photo(partner_id, update.message.photo[-1].file_id)
            await update.message.reply_text(f"✅ Фото отправлено. С вашего счёта списано {COST_FOR_PHOTO} валюты.")
        else:
            await update.message.reply_text(f"❌ Недостаточно валюты для отправки фото. Стоимость: {COST_FOR_PHOTO}. Ваш баланс: {user['balance']}.")
    elif update.message.video:
        await context.bot.send_video(partner_id, update.message.video.file_id)
    elif update.message.voice:
        await context.bot.send_voice(partner_id, update.message.voice.file_id)
