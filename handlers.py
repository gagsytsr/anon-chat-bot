import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db
import keyboards as kb
from config import (
    ADMIN_PASSWORD, ADMIN_IDS, REWARD_FOR_REFERRAL, COST_FOR_18PLUS,
    COST_FOR_UNBAN, COST_FOR_PHOTO, CHAT_TIMER_SECONDS, MAX_WARNINGS
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# --- Вспомогательные функции ---
async def show_main_menu(user_id: int, context: ContextTypes.DEFAULT_TYPE, as_admin=False):
    """Отображает главное меню, в том числе для забаненных."""
    user = await db.get_or_create_user(user_id)
    
    if user['is_banned']:
        text = (
            f"❌ **Доступ к поиску ограничен!**\n\n"
            f"Вы заблокированы, т.к. у вас {user['warnings']} из {MAX_WARNINGS} предупреждений. "
            f"Вы можете разбанить себя, чтобы сбросить счётчик."
        )
        # Отправляем инлайн-кнопку для разбана, но оставляем Reply-клавиатуру для доступа к балансу
        await context.bot.send_message(user_id, text, reply_markup=kb.get_ban_keyboard(), parse_mode='Markdown')
        await context.bot.send_message(user_id, "Вам доступны другие разделы меню.", reply_markup=kb.get_main_menu_keyboard())
        return

    text = "Главное меню:"
    keyboard = kb.get_main_menu_keyboard()
    if as_admin:
        text = "Вы вошли как администратор."
        keyboard = kb.get_admin_reply_keyboard()
    
    await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)


async def end_chat_session(user_id: int, context: ContextTypes.DEFAULT_TYPE, message_for_partner: str):
    """Завершает чат, удаляет таймер и историю чата."""
    user = await db.get_or_create_user(user_id)
    partner_id = user['partner_id']
    
    if partner_id:
        pair_key = tuple(sorted((user_id, partner_id)))
        job_name = f"chat_timer_{pair_key[0]}_{pair_key[1]}"
        jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in jobs:
            job.schedule_removal()
        # Очистка истории чата и запросов на обмен
        context.bot_data.pop(f"history_{pair_key}", None)
        context.bot_data.pop(f"exchange_{pair_key}", None)

    actual_partner_id = await db.end_chat(user_id)
    
    if actual_partner_id:
        if message_for_partner:
            await context.bot.send_message(actual_partner_id, message_for_partner, reply_markup=kb.remove_keyboard())
        is_partner_admin = actual_partner_id in ADMIN_IDS
        await show_main_menu(actual_partner_id, context, as_admin=is_partner_admin)
    
    is_admin = user_id in ADMIN_IDS
    await context.bot.send_message(user_id, "❌ Чат завершён.", reply_markup=kb.remove_keyboard())
    await show_main_menu(user_id, context, as_admin=is_admin)


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
        except Exception:
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


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        await update.message.reply_text("🔐 Админ-панель", reply_markup=kb.get_admin_keyboard())
    else:
        context.user_data["awaiting_admin_password"] = True
        await update.message.reply_text("🔐 Введите пароль администратора:")


# --- Логика таймера ---
async def ask_for_exchange(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    u1, u2 = job_data['user1'], job_data['user2']

    user1_data = await db.get_or_create_user(u1)
    if user1_data['status'] != 'in_chat' or user1_data['partner_id'] != u2:
        return

    pair_key = tuple(sorted((u1, u2)))
    context.bot_data[f"exchange_{pair_key}"] = {u1: None, u2: None}

    await context.bot.send_message(u1, "Время вышло! Хотите обменяться никами с собеседником?", reply_markup=kb.get_name_exchange_keyboard())
    await context.bot.send_message(u2, "Время вышло! Хотите обменяться никами с собеседником?", reply_markup=kb.get_name_exchange_keyboard())


# --- Обработчик кнопок (Callback) ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()
    
    if data.startswith("report_"):
        reason = data.split('_')[1]
        if reason == 'cancel':
            await query.message.delete()
            return

        user_data = await db.get_or_create_user(user_id)
        partner_id = user_data.get('partner_id')
        if not partner_id:
            await query.edit_message_text("❌ Чат уже завершён.")
            return

        pair_key = tuple(sorted((user_id, partner_id)))
        history = context.bot_data.get(f"history_{pair_key}", "История чата не найдена.")
        
        report_text = (
            f"❗️ **Новая жалоба** ❗️\n\n"
            f"👤 **От:** `{user_id}`\n"
            f"🎯 **На:** `{partner_id}`\n"
            f"📜 **Причина:** {reason.capitalize()}\n\n"
            f"📝 **История чата:**\n{history}"
        )

        if not ADMIN_IDS:
             logger.warning("Жалоба получена, но нет активных админов для ее получения!")
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, report_text, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Не удалось отправить жалобу админу {admin_id}: {e}")

        await query.message.edit_text("✅ Ваша жалоба отправлена администратору на рассмотрение.")
        return

    if data == "unban_request":
        user = await db.get_or_create_user(user_id)
        if user['balance'] >= COST_FOR_UNBAN:
            await db.update_balance(user_id, -COST_FOR_UNBAN)
            await db.set_ban_status(user_id, False)
            await query.message.edit_text(f"✅ Вы успешно разблокированы за {COST_FOR_UNBAN} монет. Ваши предупреждения сброшены.")
            await show_main_menu(user_id, context, as_admin=(user_id in ADMIN_IDS))
        else:
            await query.answer(f"❌ Недостаточно монет. Необходимо {COST_FOR_UNBAN}.", show_alert=True)
        return

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
        answer = data.split('_')[1]
        user_data = await db.get_or_create_user(user_id)
        partner_id = user_data.get('partner_id')

        if not partner_id:
            await query.message.edit_text("❌ Чат уже завершён.")
            return

        pair_key = tuple(sorted((user_id, partner_id)))
        exchange_data = context.bot_data.get(f"exchange_{pair_key}")
        if exchange_data is None:
            return

        exchange_data[user_id] = answer
        await query.message.edit_text(f"Вы выбрали: '{answer}'. Ожидаем ответа собеседника...")

        if all(response is not None for response in exchange_data.values()):
            u1, u2 = pair_key
            if exchange_data[u1] == 'yes' and exchange_data[u2] == 'yes':
                user1_info = await context.bot.get_chat(u1)
                user2_info = await context.bot.get_chat(u2)
                
                user1_name = f"@{user1_info.username}" if user1_info.username else user1_info.first_name
                user2_name = f"@{user2_info.username}" if user2_info.username else user2_info.first_name

                await context.bot.send_message(u1, f"🥳 Собеседник согласился! Его контакт: {user2_name}")
                await context.bot.send_message(u2, f"🥳 Собеседник согласился! Его контакт: {user1_name}")
            else:
                await context.bot.send_message(u1, "❌ Один из собеседников отказался. Обмен не состоялся.")
                await context.bot.send_message(u2, "❌ Один из собеседников отказался. Обмен не состоялся.")
            
            await end_chat_session(user_id, context, "")
        return

    if data == "admin_stats":
        stats = await db.get_admin_stats()
        await query.message.edit_text(
            f"📊 **Статистика Бота**\n\n"
            f"👤 Всего пользователей: {stats['total_users']}\n"
            f"💬 Активных чатов: {stats['active_chats']}\n"
            f"⛔ Забанено: {stats['banned_users']}\n"
            f"🔗 Всего рефералов: {stats['total_referrals']}\n"
            f"💰 Общий баланс: {stats['total_balance']}",
            parse_mode='Markdown',
            reply_markup=kb.get_admin_keyboard()
        )
        return

    if data == "admin_ban":
        context.user_data['awaiting_ban_id'] = True
        await query.message.edit_text("Введите ID пользователя для бана:")
        return
        
    if data == "admin_unban":
        context.user_data['awaiting_unban_id'] = True
        await query.message.edit_text("Введите ID пользователя для разбана:")
        return

    if data == "admin_add_currency":
        context.user_data['awaiting_add_currency'] = True
        await query.message.edit_text("Введите ID и сумму через пробел (например, 12345 100):")
        return

    if data == "admin_remove_currency":
        context.user_data['awaiting_remove_currency'] = True
        await query.message.edit_text("Введите ID и сумму для списания через пробел:")
        return

    if data == "admin_stop_all":
        active_users = await db.get_all_active_users()
        if not active_users:
            await query.message.edit_text("Активных чатов нет.", reply_markup=kb.get_admin_keyboard())
            return

        uids_in_chat = {record['user_id'] for record in active_users}
        for uid in uids_in_chat:
            user = await db.get_or_create_user(uid)
            if user['status'] == 'in_chat':
                await end_chat_session(uid, context, "Чат принудительно завершен администратором.")
        
        await query.message.edit_text(f"✅ Завершено чатов: {len(uids_in_chat) // 2}.", reply_markup=kb.get_admin_keyboard())
        return

    if data == "agree":
        await db.set_agreement(user_id, True)
        await query.message.delete()
        await show_main_menu(user_id, context, as_admin=(user_id in ADMIN_IDS))

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
        if user['is_banned']:
            await query.answer("❌ Вы заблокированы и не можете искать собеседника.", show_alert=True)
            await query.message.delete()
            await show_main_menu(user_id, context, as_admin=(user_id in ADMIN_IDS))
            return

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
            chat_message = f"🎉 Собеседник найден! У вас есть {CHAT_TIMER_SECONDS} секунд для общения, после чего бот предложит обменяться никами."
            await context.bot.send_message(user_id, chat_message, reply_markup=kb.get_chat_keyboard())
            await context.bot.send_message(partner_id, chat_message, reply_markup=kb.get_chat_keyboard())
            
            pair_key = tuple(sorted((user_id, partner_id)))
            context.job_queue.run_once(
                ask_for_exchange,
                CHAT_TIMER_SECONDS,
                data={'user1': user_id, 'user2': partner_id},
                name=f"chat_timer_{pair_key[0]}_{pair_key[1]}"
            )


# --- Обработчик сообщений ---
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
        
    user_id = update.effective_user.id
    text = update.message.text

    if user_id in ADMIN_IDS:
        if context.user_data.get('awaiting_ban_id'):
            try:
                target_id = int(text)
                await db.set_ban_status(target_id, True)
                await update.message.reply_text(f"✅ Пользователь {target_id} забанен.")
                await context.bot.send_message(target_id, "❌ Вы были заблокированы администратором.")
            except Exception:
                await update.message.reply_text("❌ Некорректный ID или ошибка.")
            context.user_data.pop('awaiting_ban_id')
            await admin_command(update, context)
            return
            
        if context.user_data.get('awaiting_unban_id'):
            try:
                target_id = int(text)
                await db.set_ban_status(target_id, False)
                await update.message.reply_text(f"✅ Пользователь {target_id} разбанен.")
                await context.bot.send_message(target_id, "✅ Вы были разблокированы администратором.")
            except Exception:
                await update.message.reply_text("❌ Некорректный ID или ошибка.")
            context.user_data.pop('awaiting_unban_id')
            await admin_command(update, context)
            return
            
        if context.user_data.get('awaiting_add_currency'):
            try:
                target_id, amount = map(int, text.split())
                new_balance = await db.update_balance(target_id, amount)
                await update.message.reply_text(f"✅ Пользователю {target_id} начислено {amount}. Новый баланс: {new_balance}.")
                await context.bot.send_message(target_id, f"🎉 Администратор начислил вам {amount} монет.")
            except Exception:
                await update.message.reply_text("❌ Неверный формат. Введите ID и сумму.")
            context.user_data.pop('awaiting_add_currency')
            await admin_command(update, context)
            return
            
        if context.user_data.get('awaiting_remove_currency'):
            try:
                target_id, amount = map(int, text.split())
                new_balance = await db.update_balance(target_id, -amount)
                await update.message.reply_text(f"✅ У пользователя {target_id} списано {amount}. Новый баланс: {new_balance}.")
                await context.bot.send_message(target_id, f"💸 Администратор списал у вас {amount} монет.")
            except Exception:
                await update.message.reply_text("❌ Неверный формат. Введите ID и сумму.")
            context.user_data.pop('awaiting_remove_currency')
            await admin_command(update, context)
            return

    user = await db.get_or_create_user(user_id)
    is_admin = user_id in ADMIN_IDS

    if context.user_data.get("awaiting_admin_password"):
        if text.strip() == ADMIN_PASSWORD:
            ADMIN_IDS.add(user_id)
            await update.message.reply_text("✅ Доступ разрешен.", reply_markup=kb.get_admin_reply_keyboard())
        else:
            await update.message.reply_text("❌ Неверный пароль.")
        context.user_data.pop("awaiting_admin_password", None)
        return

    if user['is_banned']:
        if text == "🔍 Поиск собеседника":
            await show_main_menu(user_id, context)
        elif text == "💰 Мой баланс":
            await update.message.reply_text(f"💰 Ваш баланс: {user['balance']} монет.", reply_markup=kb.get_balance_keyboard())
        elif text == "🔗 Мои рефералы":
            text_ref = (
                f"🔗 **Приглашайте друзей и получайте монеты!**\n\n"
                f"За каждого пользователя, который запустит бота по вашей ссылке, вы получите **{REWARD_FOR_REFERRAL} монет**.\n\n"
                f"Ваша уникальная ссылка:\n`https://t.me/{context.bot.username}?start={user_id}`"
            )
            await update.message.reply_text(text_ref, reply_markup=kb.get_back_keyboard(), parse_mode='Markdown')
        elif is_admin and text == "🔐 Админ-панель":
             await admin_command(update, context)
        else:
            await show_main_menu(user_id, context)
        return

    if text == "🔐 Админ-панель" and is_admin:
        await admin_command(update, context)
        return

    if user['status'] == 'in_chat':
        partner_id = user['partner_id']
        pair_key = tuple(sorted((user_id, partner_id)))

        if f"history_{pair_key}" not in context.bot_data:
            context.bot_data[f"history_{pair_key}"] = ""
        context.bot_data[f"history_{pair_key}"] += f"[{user_id}]: {text}\n"

        if text == "⚠️ Пожаловаться":
            await update.message.reply_text("Выберите причину жалобы:", reply_markup=kb.get_report_keyboard())
            return
        
        forbidden_keywords = ['@', 'ник', 'никнейм', 'username', 'юзернейм']
        if any(keyword in text.lower() for keyword in forbidden_keywords):
            new_warnings = await db.add_warning(user_id)
            
            await context.bot.send_message(user_id, f"⚠️ **Предупреждение {new_warnings}/{MAX_WARNINGS}**: Нельзя разглашать личную информацию.", parse_mode='Markdown')

            if new_warnings >= MAX_WARNINGS:
                await db.set_ban_status(user_id, True)
                await context.bot.send_message(user_id, "❌ **Вы были заблокированы за многократные нарушения.**", reply_markup=kb.remove_keyboard(), parse_mode='Markdown')
                await end_chat_session(user_id, context, "⚠️ Ваш собеседник был забанен за нарушение правил. Чат завершён.")
            return

        await context.bot.send_message(partner_id, text)
    else:
        if text == "🔍 Поиск собеседника":
            context.user_data["interests"] = []
            await update.message.reply_text("Выберите ваши интересы:", reply_markup=await kb.get_interests_keyboard())
        elif text == "💰 Мой баланс":
            await update.message.reply_text(f"💰 Ваш баланс: {user['balance']} монет.", reply_markup=kb.get_balance_keyboard())
        elif text == "🔗 Мои рефералы":
            text_ref = (
                f"🔗 **Приглашайте друзей и получайте монеты!**\n\n"
                f"За каждого пользователя, который запустит бота по вашей ссылке, вы получите **{REWARD_FOR_REFERRAL} монет**.\n\n"
                f"Ваша уникальная ссылка:\n`https://t.me/{context.bot.username}?start={user_id}`"
            )
            await update.message.reply_text(text_ref, reply_markup=kb.get_back_keyboard(), parse_mode='Markdown')
        else:
            await show_main_menu(user_id, context, as_admin=is_admin)


async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await db.get_or_create_user(user_id)

    if user['is_banned']:
        return

    if user['status'] == 'in_chat':
        if user['balance'] >= COST_FOR_PHOTO:
            new_balance = await db.update_balance(user_id, -COST_FOR_PHOTO)
            caption = f"✅ Медиа отправлено. Списано {COST_FOR_PHOTO} монет. Ваш баланс: {new_balance}."
            if update.message.photo:
                await context.bot.send_photo(user['partner_id'], update.message.photo[-1].file_id)
            elif update.message.video:
                await context.bot.send_video(user['partner_id'], update.message.video.file_id)
            await update.message.reply_text(caption)
        else:
            await update.message.reply_text(f"❌ Недостаточно монет для отправки медиа (нужно {COST_FOR_PHOTO}).")

