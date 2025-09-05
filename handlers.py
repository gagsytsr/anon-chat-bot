import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db
import keyboards as kb
from config import (
    ADMIN_PASSWORD, ADMIN_IDS, REWARD_FOR_REFERRAL, COST_FOR_18PLUS,
    COST_FOR_UNBAN, COST_FOR_PHOTO, CHAT_TIMER_SECONDS
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# --- Вспомогательные функции ---
async def show_main_menu(user_id: int, context: ContextTypes.DEFAULT_TYPE, as_admin=False, message_id=None):
    """Отображает главное меню, редактируя сообщение или отправляя новое."""
    text = "Главное меню:"
    keyboard = kb.get_main_menu_keyboard()
    if as_admin:
        text = "Вы вошли как администратор."
        keyboard = kb.get_admin_reply_keyboard()

    # Если есть message_id, редактируем сообщение. Иначе - отправляем новое.
    if message_id:
        try:
            await context.bot.edit_message_text(chat_id=user_id, message_id=message_id, text=text, reply_markup=None)
            # Отправляем новое сообщение с Reply-клавиатурой, так как ее нельзя прикрепить к измененному
            await context.bot.send_message(chat_id=user_id, text="​", reply_markup=keyboard, parse_mode='HTML') # Используем невидимый символ
        except Exception:
            # Если не удалось отредактировать, просто отправляем новое
            await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)


async def end_chat_session(user_id: int, context: ContextTypes.DEFAULT_TYPE, message_for_partner: str):
    # Удаляем таймер, если он был
    chat_id_str = f"chat_timer_{user_id}"
    jobs = context.job_queue.get_jobs_by_name(chat_id_str)
    for job in jobs:
        job.schedule_removal()
        
    partner_id = await db.end_chat(user_id)
    if partner_id:
        is_partner_admin = partner_id in ADMIN_IDS
        await context.bot.send_message(partner_id, message_for_partner, reply_markup=kb.remove_keyboard())
        await show_main_menu(partner_id, context, as_admin=is_partner_admin)
    
    is_admin = user_id in ADMIN_IDS
    await context.bot.send_message(user_id, "❌ Чат завершён.", reply_markup=kb.remove_keyboard())
    await show_main_menu(user_id, context, as_admin=is_admin)


# --- Обработчики команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновленный обработчик /start с правилами."""
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
    rules_text = (
        "<b>Пожалуйста, прочтите и примите правила, чтобы начать:</b>\n\n"
        "• Соблюдайте законодательство.\n"
        "• Общайтесь на темы, соответствующие выбранным интересам.\n"
        "• Запрещены оскорбления, угрозы и проявление агрессии.\n"
        "• Запрещено разглашение личной информации (ники, телефоны и т.д.)."
    )
    keyboard = [[InlineKeyboardButton("✅ Я принимаю правила", callback_data="agree")]]
    await update.message.reply_text(rules_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

# --- Логика таймера и обмена никами ---
async def ask_for_exchange(context: ContextTypes.DEFAULT_TYPE):
    """Отправляет предложение обменяться никами обоим пользователям."""
    job_data = context.job.data
    u1, u2 = job_data['user1'], job_data['user2']

    # Проверяем, что оба все еще в чате друг с другом
    user1_data = await db.get_or_create_user(u1)
    if user1_data['status'] != 'in_chat' or user1_data['partner_id'] != u2:
        return # Чат уже завершен

    context.bot_data[f"exchange_{u1}"] = None # Ожидаем ответа
    context.bot_data[f"exchange_{u2}"] = None

    await context.bot.send_message(u1, "Время вышло! Хотите обменяться никами (@username) с собеседником?", reply_markup=kb.get_name_exchange_keyboard())
    await context.bot.send_message(u2, "Время вышло! Хотите обменяться никами (@username) с собеседником?", reply_markup=kb.get_name_exchange_keyboard())


# --- Обработчик кнопок (Callback) ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data == "back_to_main":
        await query.message.delete()
        await show_main_menu(user_id, context, as_admin=(user_id in ADMIN_IDS))
        return

    if data == "earn_coins":
        text = (
            f"🔗 **Приглашайте друзей и получайте монеты!**\n\n"
            f"За каждого пользователя, который запустит бота по вашей ссылке, вы получите **{REWARD_FOR_REFERRAL} монет**.\n\n"
            f"Ваша уникальная ссылка:\n`https://t.me/{context.bot.username}?start={user_id}`"
        )
        await query.message.edit_text(text, reply_markup=kb.get_back_keyboard(), parse_mode='Markdown')
        return

    if data.startswith("exchange_"):
        answer = data.split('_')[1] # yes или no
        user_data = await db.get_or_create_user(user_id)
        partner_id = user_data.get('partner_id')

        if not partner_id:
            await query.message.edit_text("❌ Чат уже завершён.")
            return

        context.bot_data[f"exchange_{user_id}"] = answer
        await query.message.edit_text(f"Вы выбрали: '{answer}'. Ожидаем ответа собеседника...")

        partner_answer = context.bot_data.get(f"exchange_{partner_id}")
        if partner_answer: # Если партнер уже ответил
            if answer == 'yes' and partner_answer == 'yes':
                user_info = await context.bot.get_chat(user_id)
                partner_info = await context.bot.get_chat(partner_id)
                user_username = f"@{user_info.username}" if user_info.username else "скрыт"
                partner_username = f"@{partner_info.username}" if partner_info.username else "скрыт"

                await context.bot.send_message(user_id, f"🥳 Собеседник согласился! Его ник: {partner_username}")
                await context.bot.send_message(partner_id, f"🥳 Собеседник согласился! Его ник: {user_username}")
            else:
                await context.bot.send_message(user_id, "❌ Один из собеседников отказался. Обмен не состоялся. Чат завершен.")
                await context.bot.send_message(partner_id, "❌ Один из собеседников отказался. Обмен не состоялся. Чат завершен.")
            
            # Завершаем чат в любом случае после ответа обоих
            await end_chat_session(user_id, context, "")
        return

    # ... (код для админ-кнопок остается без изменений) ...

    if data == "agree":
        await db.set_agreement(user_id, True)
        await query.message.delete()
        await show_main_menu(user_id, context, as_admin=(user_id in ADMIN_IDS))

    elif data.startswith("interest_"):
        # ... (код остается без изменений) ...

    elif data == "interests_done":
        selected_interests = context.user_data.get("interests", [])
        if not selected_interests:
            await query.answer("❌ Пожалуйста, выберите хотя бы один интерес.", show_alert=True)
            return

        user = await db.get_or_create_user(user_id)
        # ... (проверка на 18+ и баланс) ...

        await db.update_user_interests(user_id, selected_interests)
        await db.update_user_status(user_id, 'waiting')
        await query.message.edit_text(f"✅ Интересы сохранены: {', '.join(selected_interests)}. Начинаем поиск...")

        partner_id = await db.find_partner(user_id, selected_interests)
        if partner_id:
            await db.create_chat(user_id, partner_id)
            chat_message = f"🎉 Собеседник найден! У вас есть {CHAT_TIMER_SECONDS} секунд для общения, после чего бот предложит обменяться никами."
            await context.bot.send_message(user_id, chat_message, reply_markup=kb.get_chat_keyboard())
            await context.bot.send_message(partner_id, chat_message, reply_markup=kb.get_chat_keyboard())
            
            # Запускаем таймер
            context.job_queue.run_once(
                ask_for_exchange,
                CHAT_TIMER_SECONDS,
                data={'user1': user_id, 'user2': partner_id},
                name=f"chat_timer_{user_id}_{partner_id}"
            )


# --- Обработчик сообщений ---
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # ... (код обработки ввода для админа остается без изменений) ...

    user = await db.get_or_create_user(user_id)
    is_admin = user_id in ADMIN_IDS

    # ... (код проверки пароля админа остается без изменений) ...

    if user['is_banned']:
        await show_main_menu(user_id, context)
        return

    if text == "🔐 Админ-панель" and is_admin:
        await admin_command(update, context)
        return
    # Логика выхода из админки удалена, так как убрана кнопка

    if user['status'] == 'in_chat':
        # Проверка на разглашение ника
        if re.search(r'@[A-Za-z0-9_]{4,}', text):
            await db.set_ban_status(user_id, True)
            await update.message.reply_text("❌ Вы были забанены за попытку разглашения личной информации.", reply_markup=kb.remove_keyboard())
            await end_chat_session(user_id, context, "⚠️ Ваш собеседник был забанен за нарушение правил. Чат завершён.")
            return

        await context.bot.send_message(user['partner_id'], text)
    else:
        if text == "🔍 Поиск собеседника":
            # ... (код без изменений) ...
        elif text == "💰 Мой баланс":
            await update.message.reply_text(f"💰 Ваш баланс: {user['balance']} монет.", reply_markup=kb.get_balance_keyboard())
        elif text == "🔗 Мои рефералы":
            text = (
                f"🔗 **Приглашайте друзей и получайте монеты!**\n\n"
                f"За каждого пользователя, который запустит бота по вашей ссылке, вы получите **{REWARD_FOR_REFERRAL} монет**.\n\n"
                f"Ваша уникальная ссылка:\n`https://t.me/{context.bot.username}?start={user_id}`"
            )
            await update.message.reply_text(text, reply_markup=kb.get_back_keyboard(), parse_mode='Markdown')
        else:
            await show_main_menu(user_id, context, as_admin=is_admin)

# ... (media_handler без изменений) ...
