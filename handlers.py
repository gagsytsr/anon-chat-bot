import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db
import keyboards as kb
from config import (
    ADMIN_PASSWORD, ADMIN_IDS, REWARD_FOR_REFERRAL, COST_FOR_18PLUS,
    COST_FOR_UNBAN, COST_FOR_PHOTO
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# --- Вспомогательные функции ---
async def show_main_menu(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    user = await db.get_or_create_user(user_id)
    if user['is_banned']:
        await context.bot.send_message(
            user_id, "❌ Вы заблокированы.", reply_markup=kb.get_ban_keyboard()
        )
    else:
        await context.bot.send_message(
            user_id, "Главное меню:", reply_markup=kb.get_main_menu_keyboard()
        )

async def end_chat_session(user_id: int, context: ContextTypes.DEFAULT_TYPE, message_for_partner: str):
    partner_id = await db.end_chat(user_id)
    if partner_id:
        await context.bot.send_message(partner_id, message_for_partner, reply_markup=kb.remove_keyboard())
        await show_main_menu(partner_id, context)
    await context.bot.send_message(user_id, "❌ Чат завершён.", reply_markup=kb.remove_keyboard())
    await show_main_menu(user_id, context)


# --- Обработчики команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await db.get_or_create_user(user_id)
    if context.args and not user['invited_by']:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user_id:
                await db.add_referral(user_id, referrer_id, REWARD_FOR_REFERRAL)
                await context.bot.send_message(referrer_id, f"🎉 По вашей ссылке пришел новый пользователь! Награда: {REWARD_FOR_REFERRAL} монет.")
        except (ValueError, IndexError):
            logger.warning(f"Некорректный ID реферера: {context.args}")

    await db.set_agreement(user_id, False)
    keyboard = [[InlineKeyboardButton("✅ Я согласен с правилами", callback_data="agree")]]
    await update.message.reply_text(
        "👋 Добро пожаловать! Пожалуйста, согласитесь с правилами.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        await update.message.reply_text("🔐 Админ-панель", reply_markup=kb.get_admin_keyboard())
    else:
        context.user_data["awaiting_admin_password"] = True
        await update.message.reply_text("🔐 Введите пароль администратора:")


# --- Обработчик кнопок ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data == "agree":
        await db.set_agreement(user_id, True)
        await query.message.delete()
        await show_main_menu(user_id, context)

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
            await query.answer("❌ Пожалуйста, выберите хотя бы один интерес.", show_alert=True)
            return

        user = await db.get_or_create_user(user_id)
        if "18+" in selected_interests and not user['unlocked_18plus']:
            if user['balance'] >= COST_FOR_18PLUS:
                await db.update_balance(user_id, -COST_FOR_18PLUS)
                await db.unlock_18plus(user_id)
            else:
                await query.message.edit_text(f"❌ Недостаточно монет для разблокировки 18+ (нужно {COST_FOR_18PLUS}). Ваш баланс: {user['balance']}.")
                return

        await db.update_user_interests(user_id, selected_interests)
        await db.update_user_status(user_id, 'waiting')
        await query.message.edit_text(f"✅ Интересы сохранены: {', '.join(selected_interests)}. Начинаем поиск...")

        partner_id = await db.find_partner(user_id, selected_interests)
        if partner_id:
            await db.create_chat(user_id, partner_id)
            await context.bot.send_message(user_id, "🎉 Собеседник найден!", reply_markup=kb.get_chat_keyboard())
            await context.bot.send_message(partner_id, "🎉 Собеседник найден!", reply_markup=kb.get_chat_keyboard())
        # Если партнер не найден, пользователь просто остается в статусе 'waiting'


# --- Обработчик сообщений ---
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    user = await db.get_or_create_user(user_id)

    if context.user_data.get("awaiting_admin_password"):
        if text.strip() == ADMIN_PASSWORD:
            ADMIN_IDS.add(user_id)
            await update.message.reply_text("✅ Доступ разрешен.", reply_markup=kb.remove_keyboard())
            await admin_command(update, context)
        else:
            await update.message.reply_text("❌ Неверный пароль.")
        context.user_data.pop("awaiting_admin_password", None)
        return

    if user['is_banned']:
        await show_main_menu(user_id, context)
        return

    if user['status'] == 'in_chat':
        if text == "🚫 Завершить чат":
            await end_chat_session(user_id, context, "Собеседник завершил чат.")
        elif text == "🔍 Начать новый чат":
            await end_chat_session(user_id, context, "Собеседник решил начать новый поиск.")
        else: # Пересылка сообщения
            await context.bot.send_message(user['partner_id'], text)
    else: # Логика для меню
        if text == "🔍 Поиск собеседника":
            context.user_data["interests"] = []
            await update.message.reply_text("Выберите ваши интересы:", reply_markup=await kb.get_interests_keyboard())
        elif text == "💰 Мой баланс":
            await update.message.reply_text(f"💰 Ваш баланс: {user['balance']} монет.")
        elif text == "🔗 Мои рефералы":
            link = f"https://t.me/{context.bot.username}?start={user_id}"
            await update.message.reply_text(f"🔗 Ваша реферальная ссылка:\n{link}\n\nПриглашено: {user['referrals_count']} чел.")
        else:
            await show_main_menu(user_id, context)

# Обработчик медиа (упрощенный)
async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await db.get_or_create_user(user_id)

    if user['status'] == 'in_chat':
        if user['balance'] >= COST_FOR_PHOTO:
            await db.update_balance(user_id, -COST_FOR_PHOTO)
            new_balance = user['balance'] - COST_FOR_PHOTO
            if update.message.photo:
                await context.bot.send_photo(user['partner_id'], update.message.photo[-1].file_id)
            elif update.message.video:
                await context.bot.send_video(user['partner_id'], update.message.video.file_id)
            await update.message.reply_text(f"✅ Медиа отправлено. Списано {COST_FOR_PHOTO} монет. Ваш баланс: {new_balance}.")
        else:
            await update.message.reply_text(f"❌ Недостаточно монет для отправки медиа (нужно {COST_FOR_PHOTO}).")
