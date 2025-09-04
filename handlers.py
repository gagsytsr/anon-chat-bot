import asyncio
import logging
import os
import re
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import database as db
import keyboards as kb

# ===== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ И КОНСТАНТЫ =====
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin") # Пароль по умолчанию для тестов
# Множество для хранения ID админов, которые сейчас онлайн в "режиме админа"
ADMIN_IDS = set() 

# --- Константы стоимости и наград ---
REWARD_FOR_REFERRAL = 10
COST_FOR_18PLUS = 50
COST_FOR_UNBAN = 100
COST_FOR_PHOTO = 50
MAX_WARNINGS = 3

# --- Словари для хранения временного состояния (существуют, пока бот запущен) ---
# Эти данные не нужно хранить в БД, так как они актуальны только в реальном времени
waiting_users = {} # {user_id: [interests]}
active_chats = {} # {user_id: partner_id}
show_name_requests = {} # {frozenset({u1, u2}): {u1: None, u2: None}}
active_tasks = {} # {frozenset({u1, u2}): asyncio.Task}
chat_history = {} # {user_id: "chat history text"}

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def get_user_info(user):
    """Собирает информацию о пользователе в одну строку."""
    return f"@{user.username}" if user.username else user.first_name

async def end_chat(context: ContextTypes.DEFAULT_TYPE, user1_id: int, user2_id: int):
    """Корректно завершает чат между двумя пользователями."""
    pair_key = frozenset({user1_id, user2_id})

    # Отменяем и удаляем таймер, если он был
    task = active_tasks.pop(pair_key, None)
    if task:
        task.cancel()
    
    # Удаляем другие связанные данные
    show_name_requests.pop(pair_key, None)
    active_chats.pop(user1_id, None)
    active_chats.pop(user2_id, None)
    chat_history.pop(user1_id, None)
    chat_history.pop(user2_id, None)
    
    # Отправляем клавиатуры, проверяя, не вышел ли кто-то из них из режима админа
    is_admin1 = user1_id in ADMIN_IDS
    is_admin2 = user2_id in ADMIN_IDS

    try:
        await context.bot.send_message(user1_id, "❌ Чат завершён.", reply_markup=kb.get_main_menu_keyboard(is_admin1))
    except Exception as e:
        logging.warning(f"Не удалось отправить сообщение о завершении чата пользователю {user1_id}: {e}")
    try:
        await context.bot.send_message(user2_id, "❌ Собеседник завершил чат.", reply_markup=kb.get_main_menu_keyboard(is_admin2))
    except Exception as e:
        logging.warning(f"Не удалось отправить сообщение о завершении чата пользователю {user2_id}: {e}")

# ===== ОБРАБОТЧИКИ КОМАНД (/start, /admin) =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.get_or_create_user(user.id, user.username, user.first_name)
    
    # Обработка реферальной ссылки
    if context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user.id:
                if await db.set_invited_by(user.id, referrer_id):
                    await db.update_balance(referrer_id, REWARD_FOR_REFERRAL)
                    await context.bot.send_message(
                        referrer_id, f"🎉 Новый пользователь по вашей ссылке! Вам начислено {REWARD_FOR_REFERRAL} монет."
                    )
        except Exception:
            pass

    await update.message.reply_text(
        "👋 Добро пожаловать в анонимный чат!\n\n"
        "⚠️ Перед началом подтвердите согласие с правилами:\n"
        "• Запрещено нарушать законы и правила Telegram.\n"
        "• Запрещено разглашать личную информацию.\n"
        "• Соблюдайте уважение к собеседнику.\n\n"
        "Нажмите 'Согласен', чтобы начать.",
        reply_markup=kb.get_start_keyboard()
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        await update.message.reply_text("👑 Админ-панель", reply_markup=kb.get_admin_keyboard())
    else:
        context.user_data['state'] = 'awaiting_admin_password'
        await update.message.reply_text("🔐 Введите пароль администратора:")

# ===== ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ (ТЕКСТ + КНОПКИ) =====
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    text = update.message.text
    state = context.user_data.get('state')

    # 1. Первым делом обновляем данные пользователя
    await db.get_or_create_user(user_id, user.username, user.first_name)
    
    # 2. Проверяем, не забанен ли пользователь
    user_data = await db.get_user_data(user_id)
    if user_data.get('is_banned'):
        if user_data.get('balance', 0) >= COST_FOR_UNBAN:
            await update.message.reply_text("❌ Вы заблокированы. Вы можете разблокировать себя, используя монеты.", reply_markup=kb.get_unban_keyboard())
        else:
            await update.message.reply_text("❌ Вы заблокированы. У вас недостаточно монет для разблокировки.")
        return

    # 3. Обработка состояний (для админ-панели)
    if state:
        context.user_data['state'] = None # Сбрасываем состояние после обработки
        if state == 'awaiting_admin_password':
            if text.strip() == ADMIN_PASSWORD:
                ADMIN_IDS.add(user_id)
                await update.message.reply_text("✅ Вход выполнен! Админ-панель доступна.", reply_markup=kb.get_main_menu_keyboard(is_admin=True))
                await admin_command(update, context)
            else:
                await update.message.reply_text("❌ Неверный пароль.")
            return
        
        target_id, *args = text.split()
        try:
            target_id = int(target_id)
        except ValueError:
            await update.message.reply_text("❌ Неверный ID. Попробуйте снова.")
            return

        if state == 'awaiting_ban_id':
            await db.ban_user(target_id)
            await update.message.reply_text(f"✅ Пользователь {target_id} забанен.")
            try:
                await context.bot.send_message(target_id, "❌ Вы были заблокированы администратором.")
            except Exception: pass
        elif state == 'awaiting_unban_id':
            await db.unban_user(target_id)
            await update.message.reply_text(f"✅ Пользователь {target_id} разбанен.")
            try:
                await context.bot.send_message(target_id, "✅ Вы были разблокированы администратором.")
            except Exception: pass
        elif state == 'awaiting_add_currency':
            try:
                amount = int(args[0])
                new_balance = await db.update_balance(target_id, amount)
                await update.message.reply_text(f"✅ Пользователю {target_id} начислено {amount} монет. Новый баланс: {new_balance}.")
                await context.bot.send_message(target_id, f"🎉 Администратор начислил вам {amount} монет.")
            except (IndexError, ValueError):
                await update.message.reply_text("❌ Неверный формат. Введите ID и сумму.")
        elif state == 'awaiting_remove_currency':
            try:
                amount = int(args[0])
                new_balance = await db.update_balance(target_id, -amount)
                await update.message.reply_text(f"✅ У пользователя {target_id} списано {amount} монет. Новый баланс: {new_balance}.")
            except (IndexError, ValueError):
                await update.message.reply_text("❌ Неверный формат. Введите ID и сумму.")
        return

    # 4. Если пользователь в чате
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        if text == "🚫 Завершить чат":
            await end_chat(context, user_id, partner_id)
        elif text == "🔍 Начать новый чат":
            await context.bot.send_message(user_id, "Сначала завершите текущий чат.")
        elif text == "⚠️ Пожаловаться":
            await update.message.reply_text("Выберите причину жалобы:", reply_markup=kb.get_report_keyboard())
        else:
            # Пересылка сообщения + проверка на личные данные
            if re.search(r'@\w+|t\.me\/\w+', text, re.IGNORECASE):
                warnings = await db.add_warning(user_id)
                if warnings >= MAX_WARNINGS:
                    await db.ban_user(user_id)
                    await update.message.reply_text(f"❌ Вы были забанены за многократные попытки разгласить личную информацию.")
                    await end_chat(context, user_id, partner_id)
                else:
                    await update.message.reply_text(f"⚠️ Предупреждение {warnings}/{MAX_WARNINGS}: Нельзя разглашать личную информацию!")
            else:
                # Обновляем историю чата
                history_line = f"<b>{user_id}</b>: {text}\n"
                chat_history[user_id] = chat_history.get(user_id, "") + history_line
                chat_history[partner_id] = chat_history.get(partner_id, "") + history_line
                # Отправляем сообщение
                await context.bot.send_message(partner_id, text)
        return

    # 5. Обработка кнопок главного меню
    if text == "🔍 Поиск собеседника":
        context.user_data['selected_interests'] = []
        await update.message.reply_text("Выберите ваши интересы, чтобы найти подходящего собеседника:", reply_markup=kb.get_interests_keyboard())
    elif text == "💰 Мой баланс":
        balance = user_data.get('balance', 0)
        await update.message.reply_text(f"💰 Ваш текущий баланс: {balance} монет.")
    elif text == "🔗 Мои рефералы":
        ref_count = await db.get_referral_count(user_id)
        link = f"https://t.me/{context.bot.username}?start={user_id}"
        await update.message.reply_text(f"🔗 Ваша ссылка: {link}\n👥 Приглашено: {ref_count}")
    elif text == "👑 Админ-панель" and user_id in ADMIN_IDS:
        await admin_command(update, context)
    else:
        # Ответ по умолчанию, если не в чате и не команда
        await update.message.reply_text("Используйте кнопки меню для навигации.", reply_markup=kb.get_main_menu_keyboard(is_admin=user_id in ADMIN_IDS))

# ===== ОБРАБОТЧИК МЕДИА-ФАЙЛОВ (ФОТО, ВИДЕО, ГОЛОСОВЫЕ) =====
async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        message = update.message
        
        # Плата за фото
        if message.photo:
            user_data = await db.get_user_data(user_id)
            if user_data.get('balance', 0) >= COST_FOR_PHOTO:
                await db.update_balance(user_id, -COST_FOR_PHOTO)
                await context.bot.send_photo(partner_id, message.photo[-1].file_id, caption=message.caption)
                await message.reply_text(f"✅ Фото отправлено. Списано {COST_FOR_PHOTO} монет.")
            else:
                await message.reply_text(f"❌ Недостаточно монет для отправки фото. Нужно: {COST_FOR_PHOTO}.")
        # Бесплатная пересылка остальных медиа
        elif message.video:
            await context.bot.send_video(partner_id, message.video.file_id, caption=message.caption)
        elif message.voice:
            await context.bot.send_voice(partner_id, message.voice.file_id, caption=message.caption)
        elif message.sticker:
            await context.bot.send_sticker(partner_id, message.sticker.file_id)

# ===== ОБРАБОТЧИК НАЖАТИЙ НА INLINE-КНОПКИ =====
async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    # --- Согласие с правилами ---
    if data == "agree":
        await query.message.delete()
        is_admin = user_id in ADMIN_IDS
        await query.message.reply_text("✅ Отлично! Теперь можно начать.", reply_markup=kb.get_main_menu_keyboard(is_admin))
        return

    # --- Разбан за монеты ---
    if data == "unban_request":
        user_data = await db.get_user_data(user_id)
        if user_data.get('balance', 0) >= COST_FOR_UNBAN:
            await db.update_balance(user_id, -COST_FOR_UNBAN)
            await db.unban_user(user_id)
            await query.edit_message_text("✅ Вы успешно разблокированы! Теперь бот снова доступен.")
        else:
            await query.edit_message_text(f"❌ Недостаточно монет. Необходимо {COST_FOR_UNBAN}.")
        return

    # --- Выбор интересов и поиск ---
    if data.startswith("interest_"):
        interest = data.replace("interest_", "")
        selected = context.user_data.get("selected_interests", [])
        if interest in selected: selected.remove(interest)
        else: selected.append(interest)
        context.user_data["selected_interests"] = selected
        await query.edit_message_reply_markup(reply_markup=kb.get_interests_keyboard(selected))

    elif data == "interests_done":
        interests = context.user_data.get("selected_interests", [])
        if not interests:
            await context.bot.send_message(user_id, "❌ Пожалуйста, выберите хотя бы один интерес.")
            return

        # Проверка на 18+
        if "18+" in interests:
            user_data = await db.get_user_data(user_id)
            if not user_data.get('unlocked_18plus'):
                if user_data.get('balance', 0) >= COST_FOR_18PLUS:
                    await db.update_balance(user_id, -COST_FOR_18PLUS)
                    await db.unlock_18plus(user_id)
                    await query.edit_message_text(f"✅ Вы разблокировали категорию 18+ за {COST_FOR_18PLUS} монет!")
                else:
                    await context.bot.send_message(user_id, f"❌ Недостаточно монет для разблокировки 18+. Нужно: {COST_FOR_18PLUS}.")
                    return
        
        await query.edit_message_text(f"✅ Ваши интересы: {', '.join(interests)}. Ищем собеседника...")
        # Поиск партнера
        partner_id = None
        for p_id, p_interests in waiting_users.items():
            if p_id != user_id and set(interests) & set(p_interests):
                partner_id = p_id
                break
        
        if partner_id:
            del waiting_users[partner_id]
            await start_chat(context, user_id, partner_id)
        else:
            waiting_users[user_id] = interests
            await context.bot.send_message(user_id, "⏳ Никого не найдено. Мы уведомим вас, как только кто-то появится.")

    # --- Обработка событий в чате (показ имени, жалоба) ---
    elif data == "show_name_yes" or data == "show_name_no":
        await handle_show_name_request(query, context, agree=(data == "show_name_yes"))

    elif data.startswith("report_reason_"):
        reason = data.split('_', 2)[-1]
        partner_id = active_chats.get(user_id)
        if not partner_id:
            await query.edit_message_text("❌ Не удалось отправить жалобу, чат уже завершен.")
            return

        report_text = (
            f"❗️ **НОВАЯ ЖАЛОБА** ❗️\n\n"
            f"От: `{user_id}`\n"
            f"На: `{partner_id}`\n"
            f"Причина: `{reason}`\n\n"
            f"**История чата:**\n"
            f"```{chat_history.get(user_id, 'История пуста.')}```"
        )
        for admin_id in ADMIN_IDS: # Отправляем только активным админам
            await context.bot.send_message(admin_id, report_text, parse_mode=ParseMode.MARKDOWN)

        await query.edit_message_text("✅ Ваша жалоба отправлена. Чат будет завершен.")
        await end_chat(context, user_id, partner_id)
    
    # --- Админ-панель ---
    elif data == "admin_stats":
        stats = await db.get_stats()
        active_pairs = len(active_chats) // 2
        stats_text = (
            f"📊 **Статистика бота**\n\n"
            f"👤 Всего пользователей: {stats['total_users']}\n"
            f"💬 Активных чатов (пар): {active_pairs}\n"
            f"⛔ Забанено: {stats['banned_users']}\n"
            f"💰 Общий баланс в системе: {stats['total_balance']}\n"
            f"🔗 Всего приглашений: {stats['total_referrals']}"
        )
        await query.edit_message_text(stats_text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb.get_admin_keyboard())
    elif data == "admin_ban":
        context.user_data['state'] = 'awaiting_ban_id'
        await query.message.reply_text("Введите ID пользователя для бана:")
    elif data == "admin_unban":
        context.user_data['state'] = 'awaiting_unban_id'
        await query.message.reply_text("Введите ID пользователя для разбана:")
    elif data == "admin_add_currency":
        context.user_data['state'] = 'awaiting_add_currency'
        await query.message.reply_text("Введите ID и сумму через пробел (e.g., `12345 100`):")
    elif data == "admin_remove_currency":
        context.user_data['state'] = 'awaiting_remove_currency'
        await query.message.reply_text("Введите ID и сумму через пробел (e.g., `12345 50`):")
    elif data == "admin_stop_all":
        # Копируем ключи, чтобы избежать ошибки изменения словаря во время итерации
        users_in_chat = list(active_chats.keys())
        for uid in users_in_chat:
            if uid in active_chats: # Проверяем, не был ли чат уже завершен
                partner_id = active_chats[uid]
                await end_chat(context, uid, partner_id)
        await query.message.reply_text(f"✅ Все {len(users_in_chat) // 2} чаты были завершены.")
    elif data == "admin_exit":
        ADMIN_IDS.discard(user_id)
        await query.message.delete()
        await context.bot.send_message(user_id, "🚪 Вы вышли из режима администратора.", reply_markup=kb.get_main_menu_keyboard(is_admin=False))

# ===== ЛОГИКА ТАЙМЕРА И ПОКАЗА ИМЕНИ В ЧАТЕ =====
async def chat_timer_task(context: ContextTypes.DEFAULT_TYPE, user1_id: int, user2_id: int):
    """Задача, которая ждет 10 минут и затем запускает опрос о показе имени."""
    try:
        await asyncio.sleep(600) # 10 минут
        pair_key = frozenset({user1_id, user2_id})
        # Проверяем, что чат все еще активен
        if pair_key in active_tasks:
            await ask_to_show_name(context, user1_id, user2_id)
    except asyncio.CancelledError:
        logging.info(f"Таймер для чата {user1_id}-{user2_id} отменен.")

async def start_chat(context: ContextTypes.DEFAULT_TYPE, user1_id: int, user2_id: int):
    """Начинает чат и запускает 10-минутный таймер."""
    active_chats[user1_id] = user2_id
    active_chats[user2_id] = user1_id
    
    await context.bot.send_message(user1_id, "🎉 Собеседник найден! У вас есть 10 минут анонимного общения, после чего бот предложит обменяться никами.", reply_markup=kb.get_chat_keyboard())
    await context.bot.send_message(user2_id, "🎉 Собеседник найден!", reply_markup=kb.get_chat_keyboard())
    
    # Запускаем таймер
    pair_key = frozenset({user1_id, user2_id})
    task = asyncio.create_task(chat_timer_task(context, user1_id, user2_id))
    active_tasks[pair_key] = task

async def ask_to_show_name(context: ContextTypes.DEFAULT_TYPE, user1_id: int, user2_id: int):
    """Отправляет обоим пользователям запрос на показ имени."""
    pair_key = frozenset({user1_id, user2_id})
    show_name_requests[pair_key] = {user1_id: None, user2_id: None}
    
    keyboard = kb.get_show_name_keyboard()
    await context.bot.send_message(user1_id, "⏳ 10 минут прошло. Хотите показать свой ник собеседнику?", reply_markup=keyboard)
    await context.bot.send_message(user2_id, "⏳ 10 минут прошло. Хотите показать свой ник собеседнику?", reply_markup=keyboard)

async def handle_show_name_request(query, context, agree: bool):
    """Обрабатывает ответы пользователей на запрос о показе имени."""
    user_id = query.from_user.id
    partner_id = active_chats.get(user_id)
    if not partner_id: return

    pair_key = frozenset({user_id, partner_id})
    requests = show_name_requests.get(pair_key)
    if requests is None: return

    requests[user_id] = agree
    await query.edit_message_text(f"Вы {'согласились' if agree else 'отказались'} показать ник. Ожидаем ответа собеседника...")

    # Если оба ответили
    if all(r is not None for r in requests.values()):
        u1, u2 = pair_key
        u1_agreed = requests[u1]
        u2_agreed = requests[u2]

        if u1_agreed and u2_agreed:
            u1_info = await context.bot.get_chat(u1)
            u2_info = await context.bot.get_chat(u2)
            await context.bot.send_message(u1, f"🥳 Собеседник согласен! Его ник: {get_user_info(u2_info)}")
            await context.bot.send_message(u2, f"🥳 Собеседник согласен! Его ник: {get_user_info(u1_info)}")
        else:
            await context.bot.send_message(u1, "❌ Один из собеседников отказался. Чат будет завершен.")
            await context.bot.send_message(u2, "❌ Один из собеседников отказался. Чат будет завершен.")
            await end_chat(context, u1, u2)
        
        del show_name_requests[pair_key]
