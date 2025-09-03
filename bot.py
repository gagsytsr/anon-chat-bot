import asyncio
import logging
import os
import re
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
import requests

# ===== НАСТРОЙКИ ЛОГИРОВАНИЯ =====
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ===== ПЕРЕМЕННЫЕ =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ADMIN_IDS = set()

# Переменная для API ключа Hugging Face.
HUGGING_FACE_TOKEN = os.environ.get("HUGGING_FACE_TOKEN")

if not BOT_TOKEN or not ADMIN_PASSWORD:
    logging.error("BOT_TOKEN или ADMIN_PASSWORD не установлены!")
    exit(1)

# Словари для хранения информации
waiting_users = []
active_chats = {}
show_name_requests = {}
user_agreements = {}
banned_users = set()
reported_users = {}
search_timeouts = {}
user_interests = {}
referrals = {}
invited_by = {}
user_balance = {}
unlocked_18plus = set()
warnings = {}
chat_history = {}
chat_timers = {}

# Добавлено для хранения задач-таймеров
active_tasks = {}

# Обновленный список интересов с эмодзи
available_interests = {
    "Музыка": "🎵", "Игры": "🎮", "Кино": "🎬",
    "Путешествия": "✈️", "Общение": "💬", "18+": "🔞"
}

# ===== КОНСТАНТЫ =====
REWARD_FOR_REFERRAL = 10
COST_FOR_18PLUS = 50
COST_FOR_UNBAN = 100
COST_FOR_PHOTO = 50
MAX_WARNINGS = 3
HUGGING_FACE_API_URL = "https://api-inference.huggingface.co/models/microsoft/DialoGPT-small"

# ====== СТАРТ ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /start.
    """
    user_id = update.effective_user.id
    
    if user_id in banned_users:
        await show_main_menu(user_id, context)
        return
    
    if user_id not in user_balance:
        user_balance[user_id] = 0

    if context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user_id and user_id not in invited_by:
                referrals[referrer_id] = referrals.get(referrer_id, 0) + 1
                invited_by[user_id] = referrer_id
                user_balance[referrer_id] = user_balance.get(referrer_id, 0) + REWARD_FOR_REFERRAL
                await context.bot.send_message(referrer_id, f"🎉 Новый пользователь по вашей ссылке! Вам начислено {REWARD_FOR_REFERRAL} валюты.")
        except (ValueError, IndexError):
            pass

    user_agreements[user_id] = False
    keyboard = [[InlineKeyboardButton("✅ Согласен", callback_data="agree")]]
    await update.message.reply_text(
        "👋 Добро пожаловать в анонимный чат!\n\n"
        "⚠️ Перед началом подтвердите согласие с правилами:\n"
        "• Запрещено нарушать законы.\n"
        "• Соблюдайте уважение.\n\n"
        "Нажмите 'Согласен' чтобы начать.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ====== CALLBACK ОБРАБОТЧИК ======
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик всех кнопок Inline.
    """
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data == "unban_request":
        if user_balance.get(user_id, 0) >= COST_FOR_UNBAN:
            user_balance[user_id] -= COST_FOR_UNBAN
            banned_users.discard(user_id)
            warnings[user_id] = 0
            await query.edit_message_text(f"✅ Вы успешно разблокированы за {COST_FOR_UNBAN} валюты. Ваш текущий баланс: {user_balance.get(user_id, 0)}. Счётчик предупреждений сброшен.")
            await show_main_menu(user_id, context)
        else:
            await query.edit_message_text(f"❌ Недостаточно валюты для разблокировки. Необходимо {COST_FOR_UNBAN}. Ваш баланс: {user_balance.get(user_id, 0)}.")
        return
    
    if data == "agree":
        user_agreements[user_id] = True
        await query.message.delete()
        await show_main_menu(user_id, context)

    elif data.startswith("interest_"):
        interest_key = data.replace("interest_", "")
        if interest_key in user_interests.get(user_id, []):
            user_interests[user_id].remove(interest_key)
        else:
            user_interests.setdefault(user_id, []).append(interest_key)

        await update_interests_menu(user_id, query)

    elif data == "interests_done":
        selected_interests = user_interests.get(user_id, [])
        interest_names = [name for name, _ in available_interests.items() if name in selected_interests]

        if not selected_interests:
            await query.edit_message_text("❌ Пожалуйста, выберите хотя бы один интерес.",
                                          reply_markup=await get_interests_keyboard(user_id))
            return
        
        if user_id in banned_users:
            await query.edit_message_text("❌ Вы заблокированы и не можете искать собеседников.")
            return

        if "18+" in selected_interests and user_id not in unlocked_18plus:
            if user_balance.get(user_id, 0) >= COST_FOR_18PLUS:
                user_balance[user_id] -= COST_FOR_18PLUS
                unlocked_18plus.add(user_id)
                await query.edit_message_text(
                    f"✅ Вы разблокировали чат 18+ за {COST_FOR_18PLUS} валюты. Теперь он доступен навсегда!\n"
                    f"Ваши интересы: {', '.join(interest_names) or 'Не выбраны'}.\nИщем собеседника..."
                )
            else:
                await query.edit_message_text(
                    f"❌ Недостаточно валюты для разблокировки чата 18+ (необходимо {COST_FOR_18PLUS}). Ваш баланс: {user_balance.get(user_id, 0)}."
                )
                user_interests[user_id].remove("18+")
                return
        else:
             await query.edit_message_text(
                f"✅ Ваши интересы: {', '.join(interest_names) or 'Не выбраны'}.\nИщем собеседника..."
            )
        
        await find_partner(context, user_id)

    elif data == "show_name_yes":
        await query.message.edit_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ Вы выбрали показать ник. Ждем собеседника...")
        await handle_show_name_request(user_id, context, True)

    elif data == "show_name_no":
        await query.message.edit_reply_markup(reply_markup=None)
        await query.message.reply_text("❌ Вы выбрали не показывать ник. Чат остается анонимным.")
        await handle_show_name_request(user_id, context, False)
    
    elif data.startswith("report_reason_"):
        reason = data.replace("report_reason_", "")
        partner_id = active_chats.get(user_id)
        if not partner_id:
            await query.message.reply_text("❌ Чат уже завершён или не существует.")
            return

        report_text = f"❗ **Жалоба**\n" \
                      f"От пользователя: `{user_id}`\n" \
                      f"На пользователя: `{partner_id}`\n" \
                      f"Причина: `{reason}`\n\n" \
                      f"**История чата:**\n{chat_history.get(user_id, 'История чата не найдена.')}"
        
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(admin_id, report_text, parse_mode='Markdown')
        
        await query.message.reply_text("✅ Ваша жалоба отправлена администратору. Чат будет завершён.")
        await end_chat(user_id, context)

    # ==== АДМИНКА ====
    elif data == "admin_stats":
        total_users = len([u for u in user_agreements if user_agreements[u]])
        active_pairs = len(active_chats) // 2
        await query.message.reply_text(
            f"📊 Пользователей: {total_users}\n💬 Активных чатов: {active_pairs}\n"
            f"⚠️ Жалоб: {len(reported_users)}\n⛔ Забанено: {len(banned_users)}\n"
            f"🔗 Рефералов: {sum(referrals.values())}\n💰 Общий баланс: {sum(user_balance.values())}"
        )

    elif data == "admin_stop_all":
        for uid in list(active_chats.keys()):
            await end_chat(uid, context)
        await query.message.reply_text("🚫 Все чаты завершены.")

    elif data == "admin_ban":
        await query.message.reply_text("Введите ID для бана:")
        context.user_data["awaiting_ban_id"] = True

    elif data == "admin_unban":
        await query.message.reply_text("Введите ID для разбана:")
        context.user_data["awaiting_unban_id"] = True

    elif data == "admin_add_currency":
        await query.message.reply_text("Введите ID и сумму через пробел (например, 123456789 100):")
        context.user_data["awaiting_add_currency"] = True

    elif data == "admin_remove_currency":
        await query.message.reply_text("Введите ID и сумму через пробел (например, 123456789 50):")
        context.user_data["awaiting_remove_currency"] = True

    elif data == "admin_exit":
        ADMIN_IDS.discard(user_id)
        await query.message.reply_text("🚪 Вы вышли из админ-панели.", reply_markup=ReplyKeyboardRemove())

# ====== МЕНЮ ИНТЕРЕСОВ ======
async def get_interests_keyboard(user_id):
    """
    Создает клавиатуру для выбора интересов.
    """
    keyboard = []
    selected_interests = user_interests.get(user_id, [])
    for interest, emoji in available_interests.items():
        text = f"✅ {interest} {emoji}" if interest in selected_interests else f"{interest} {emoji}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"interest_{interest}")])
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    return InlineKeyboardMarkup(keyboard)

async def update_interests_menu(user_id, query):
    """
    Обновляет кнопки выбора интересов.
    """
    await query.edit_message_reply_markup(reply_markup=await get_interests_keyboard(user_id))

# ====== МЕНЮ ОСНОВНОЕ ======
async def show_main_menu(user_id, context):
    """
    Отправляет главное меню пользователю.
    """
    if user_id in banned_users:
        keyboard = [[InlineKeyboardButton(f"Разблокировать за {COST_FOR_UNBAN} валюты", callback_data="unban_request")]]
        await context.bot.send_message(user_id, "❌ Вы заблокированы. Чтобы получить доступ к боту, вы должны разблокировать себя.", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        keyboard = [["🔍 Поиск собеседника"], ["💰 Мой баланс"], ["🔗 Мои рефералы"]]
        await context.bot.send_message(user_id, "Выберите действие:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

# ====== ПОИСК СОБЕСЕДНИКА ======
async def show_interests_menu(update, user_id):
    """
    Показывает меню выбора интересов.
    """
    if user_id in banned_users:
        await update.message.reply_text("❌ Вы заблокированы и не можете искать собеседников.")
        return
    
    if user_id in active_chats:
        await update.message.reply_text("❌ Вы уже в чате. Пожалуйста, завершите его, чтобы начать новый.")
        return

    user_interests[user_id] = []
    await update.message.reply_text("Выберите интересы, чтобы найти подходящего собеседника:", reply_markup=await get_interests_keyboard(user_id))

async def find_partner(context, user_id):
    """
    Ищет собеседника по интересам.
    """
    user_interests_set = set(user_interests.get(user_id, []))
    
    for waiting_user_id in list(waiting_users):
        waiting_user_interests_set = set(user_interests.get(waiting_user_id, []))
        if user_interests_set & waiting_user_interests_set:
            waiting_users.remove(waiting_user_id)
            await start_chat(context, user_id, waiting_user_id)
            return

    if user_id not in waiting_users:
        waiting_users.append(user_id)
        
    await context.bot.send_message(user_id, "⏳ Ищем собеседника с похожими интересами...")

# ====== НОВАЯ ФУНКЦИЯ ДЛЯ ЗАПУСКА ТАЙМЕРА ======
async def chat_timer_task(context, u1, u2):
    try:
        await asyncio.sleep(600)  # Ждём 10 минут
        if u1 in active_chats and active_chats[u1] == u2:
            await ask_to_show_name(context, u1, u2)
    except asyncio.CancelledError:
        pass

async def start_chat(context, u1, u2):
    """
    Начинает чат между двумя пользователями.
    """
    active_chats[u1] = u2
    active_chats[u2] = u1
    
    markup = ReplyKeyboardMarkup(
        [["🚫 Завершить чат"], ["🔍 Начать новый чат"], ["⚠️ Пожаловаться"], ["💡 Идея для разговора"]],
        resize_keyboard=True
    )

    await context.bot.send_message(u1, "🎉 Собеседник найден! У вас есть 10 минут, чтобы решить, хотите ли вы обменяться никами.", reply_markup=markup)
    await context.bot.send_message(u2, "🎉 Собеседник найден! У вас есть 10 минут, чтобы решить, хотите ли вы обменяться никами.", reply_markup=markup)
    
    task = asyncio.create_task(chat_timer_task(context, u1, u2))
    pair_key = tuple(sorted((u1, u2)))
    active_tasks[pair_key] = task


def update_chat_history(user_id, partner_id, message):
    if user_id not in chat_history:
        chat_history[user_id] = ""
    if partner_id not in chat_history:
        chat_history[partner_id] = ""
    
    history_message = f"**{user_id}**: {message}\n"
    chat_history[user_id] += history_message
    chat_history[partner_id] += history_message

async def ask_to_show_name(context: ContextTypes.DEFAULT_TYPE, u1, u2):
    """
    Спрашивает пользователей, хотят ли они показать ники, через 10 минут.
    """
    if u1 in active_chats and active_chats[u1] == u2:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, показать ник", callback_data="show_name_yes")],
            [InlineKeyboardButton("❌ Нет, не показывать", callback_data="show_name_no")]
        ])
        
        show_name_requests[(u1, u2)] = {u1: None, u2: None}
        
        await context.bot.send_message(u1, "⏳ Прошло 10 минут. Хотите показать свой ник собеседнику?", reply_markup=keyboard)
        await context.bot.send_message(u2, "⏳ Прошло 10 минут. Хотите показать свой ник собеседнику?", reply_markup=keyboard)
        
        try:
            await asyncio.sleep(180) # Ждём 3 минуты
            if u1 in active_chats and active_chats[u1] == u2:
                pair_key = tuple(sorted((u1, u2)))
                if pair_key in show_name_requests:
                    await end_chat(u1, context)
                    await context.bot.send_message(u1, "⚠️ Время на принятие решения истекло. Чат завершён.")
                    await context.bot.send_message(u2, "⚠️ Время на принятие решения истекло. Чат завершён.")
        except asyncio.CancelledError:
            pass


async def handle_show_name_request(user_id, context, agreement):
    """
    Обрабатывает ответы на запрос о показе ника.
    """
    partner_id = active_chats.get(user_id)
    if not partner_id:
        return

    pair_key = tuple(sorted((user_id, partner_id)))
    
    if pair_key not in show_name_requests:
        return
        
    show_name_requests[pair_key][user_id] = agreement
    
    u1_agree = show_name_requests[pair_key].get(pair_key[0])
    u2_agree = show_name_requests[pair_key].get(pair_key[1])
    
    if u1_agree is not None and u2_agree is not None:
        # Отменяем задачу таймера, так как оба пользователя уже ответили
        task = active_tasks.pop(pair_key, None)
        if task:
            task.cancel()

        if u1_agree and u2_agree:
            u1_info = await context.bot.get_chat(pair_key[0])
            u2_info = await context.bot.get_chat(pair_key[1])
            
            u1_name = f"@{u1_info.username}" if u1_info.username else u1_info.first_name
            u2_name = f"@{u2_info.username}" if u2_info.username else u2_info.first_name
            
            await context.bot.send_message(pair_key[0], f"🥳 Отлично! Собеседник согласился. Его ник: {u2_name}\n\nВы можете продолжить общение в этом же чате.")
            await context.bot.send_message(pair_key[1], f"🥳 Отлично! Собеседник согласился. Его ник: {u1_name}\n\nВы можете продолжить общение в этом же чате.")
        else:
            await context.bot.send_message(pair_key[0], "😔 Собеседник отказался. Чат остаётся анонимным.")
            await context.bot.send_message(pair_key[1], "😔 Собеседник отказался. Чат остаётся анонимным.")
            await end_chat(user_id, context)
            
        del show_name_requests[pair_key]

# ====== AI функция ======
async def get_ai_response(prompt):
    """
    Отправляет запрос к Hugging Face API и возвращает ответ.
    """
    if not HUGGING_FACE_TOKEN:
        return "❌ Ошибка: API ключ не установлен. Пожалуйста, установите переменную окружения HUGGING_FACE_TOKEN."

    headers = {"Authorization": f"Bearer {HUGGING_FACE_TOKEN}"}
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 50,
            "return_full_text": False
        }
    }
    
    try:
        response = requests.post(HUGGING_FACE_API_URL, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        if isinstance(result, list) and len(result) > 0 and 'generated_text' in result[0]:
            return result[0]['generated_text']
        else:
            return "❌ Не удалось получить ответ от AI. Попробуйте еще раз."
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка запроса к Hugging Face API: {e}")
        return f"❌ Произошла ошибка при запросе к AI: {e}"

async def ai_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает запрос пользователя для получения идеи для разговора.
    """
    user_id = update.effective_user.id
    if user_id in active_chats:
        partner_id = active_chats[user_id]
        
        prompt = "Сгенерируй 5 коротких идей для разговора на русском языке, без лишних слов, просто список:"
        await context.bot.send_message(user_id, "⏳ Генерирую идеи...")
        
        response_text = await get_ai_response(prompt)
        
        await context.bot.send_message(user_id, f"💡 **Идеи для разговора**:\n{response_text}", parse_mode='Markdown')
        await context.bot.send_message(partner_id, f"💡 **Идеи для разговора**:\n{response_text}", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Вы можете получить идеи для разговора только находясь в активном чате.")

# ====== ОБРАБОТЧИК СООБЩЕНИЙ ======
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает текстовые сообщения и команды.
    """
    user_id = update.effective_user.id
    text = update.message.text
    
    if text == "🔍 Поиск собеседника" and user_id in banned_users:
        await update.message.reply_text("❌ Вы заблокированы и не можете искать собеседников.")
        return

    # Обработка админ-команд
    if context.user_data.get("awaiting_admin_password"):
        if text.strip() == ADMIN_PASSWORD:
            ADMIN_IDS.add(user_id)
            await show_admin_menu(update)
        else:
            await update.message.reply_text("❌ Неверный пароль.")
        context.user_data["awaiting_admin_password"] = False
        return
    if context.user_data.get("awaiting_ban_id"):
        try:
            target_id = int(text)
            banned_users.add(target_id)
            await update.message.reply_text(f"✅ Пользователь {target_id} забанен.")
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"Разблокировать за {COST_FOR_UNBAN} валюты", callback_data="unban_request")]])
            await context.bot.send_message(target_id, "❌ Вы были заблокированы администратором. Чтобы получить доступ к боту, вы должны разблокировать себя.", reply_markup=keyboard)
        except ValueError:
            await update.message.reply_text("❌ Неверный ID.")
        context.user_data.pop("awaiting_ban_id")
        return
    if context.user_data.get("awaiting_unban_id"):
        try:
            target_id = int(text)
            banned_users.discard(target_id)
            warnings[target_id] = 0
            await update.message.reply_text(f"✅ Пользователь {target_id} разбанен.")
            await context.bot.send_message(target_id, "✅ Вы были разблокированы администратором. Счётчик предупреждений сброшен.")
        except ValueError:
            await update.message.reply_text("❌ Неверный ID.")
        context.user_data.pop("awaiting_unban_id")
        return
    if context.user_data.get("awaiting_add_currency"):
        try:
            target_id, amount = map(int, text.split())
            user_balance[target_id] = user_balance.get(target_id, 0) + amount
            await update.message.reply_text(f"✅ Пользователю {target_id} начислено {amount} валюты. Новый баланс: {user_balance[target_id]}.")
            await context.bot.send_message(target_id, f"🎉 Администратор начислил вам {amount} валюты. Ваш баланс: {user_balance[target_id]}.")
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Неверный формат. Попробуйте еще раз.")
        context.user_data.pop("awaiting_add_currency")
        return
    if context.user_data.get("awaiting_remove_currency"):
        try:
            target_id, amount = map(int, text.split())
            user_balance[target_id] = user_balance.get(target_id, 0) - amount
            user_balance[target_id] = max(0, user_balance[target_id])
            await update.message.reply_text(f"✅ У пользователя {target_id} изъято {amount} валюты. Новый баланс: {user_balance[target_id]}.")
            await context.bot.send_message(target_id, f"⚠️ Администратор изъял у вас {amount} валюты. Ваш баланс: {user_balance[target_id]}.")
        except (ValueError, IndexError):
            await update.message.reply_text("❌ Неверный формат. Попробуйте еще раз.")
        context.user_data.pop("awaiting_remove_currency")
        return

    # Обработка команд из главного меню
    if text == "🔍 Поиск собеседника":
        await show_interests_menu(update, user_id)
    elif text == "⚠️ Пожаловаться":
        if user_id in active_chats:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Не по теме комнаты", callback_data="report_reason_off_topic")],
                [InlineKeyboardButton("Оскорбления", callback_data="report_reason_insult")],
                [InlineKeyboardButton("Неприемлемый контент", callback_data="report_reason_content")],
                [InlineKeyboardButton("Разглашение личной информации", callback_data="report_reason_private_info")]
            ])
            await update.message.reply_text("Выберите причину жалобы:", reply_markup=keyboard)
        else:
            await update.message.reply_text("❌ Вы не в чате и не можете отправить жалобу.")
    elif text == "🔗 Мои рефералы":
        link = f"https://t.me/{context.bot.username}?start={user_id}"
        await update.message.reply_text(f"🔗 Ваша ссылка: {link}\n👥 Приглашено: {referrals.get(user_id, 0)}")
    elif text == "💰 Мой баланс":
        balance = user_balance.get(user_id, 0)
        await update.message.reply_text(f"💰 Ваш текущий баланс: {balance}")
    elif text == "💡 Идея для разговора":
        await ai_handler(update, context)

    # Обработка команд из чата
    elif user_id in active_chats:
        partner_id = active_chats[user_id]
        
        if partner_id in banned_users:
            del active_chats[user_id]
            await update.message.reply_text("❌ Чат завершён. Ваш собеседник был забанен.", reply_markup=ReplyKeyboardRemove())
            await show_main_menu(user_id, context)
            return

        if text == "🚫 Завершить чат":
            await end_chat(user_id, context)
        elif text == "🔍 Начать новый чат":
            await end_chat(user_id, context)
            await show_interests_menu(update, user_id)
        else:
            update_chat_history(user_id, partner_id, text)
            
            if re.search(r'@?\s*[A-Za-z0-9_]{5,}', text) or any(s in text.lower() for s in ['ник', 'username', 'telegram']):
                warnings[user_id] = warnings.get(user_id, 0) + 1
                if warnings[user_id] >= MAX_WARNINGS:
                    banned_users.add(user_id)
                    del active_chats[partner_id]
                    del active_chats[user_id]
                    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"Разблокировать за {COST_FOR_UNBAN} валюты", callback_data="unban_request")]])
                    await update.message.reply_text(f"❌ Вы были забанены за многократные попытки разгласить личную информацию. Чтобы разблокироваться, оплатите {COST_FOR_UNBAN} валюты.", reply_markup=keyboard)
                    await context.bot.send_message(partner_id, "❌ Собеседник был забанен за нарушение правил.")
                    del chat_history[user_id]
                    del chat_history[partner_id]
                    await show_main_menu(partner_id, context)
                else:
                    await update.message.reply_text(f"⚠️ Предупреждение {warnings[user_id]}/{MAX_WARNINGS}: Нельзя разглашать личную информацию. Ещё {MAX_WARNINGS - warnings[user_id]} предупреждений до бана.")
            else:
                await context.bot.send_message(partner_id, text)

# ====== ОБРАБОТЧИК МЕДИА ======
async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает отправку фото, видео и т.д.
    """
    user_id = update.effective_user.id
    if user_id in banned_users:
        return
    
    if user_id in active_chats:
        partner = active_chats[user_id]
        if partner in banned_users:
            await update.message.reply_text("❌ Ваш собеседник был забанен. Чат завершён.")
            await end_chat(user_id, context)
            await show_main_menu(user_id, context)
            return

        if update.message.photo:
            if user_balance.get(user_id, 0) >= COST_FOR_PHOTO:
                user_balance[user_id] -= COST_FOR_PHOTO
                await context.bot.send_photo(partner, update.message.photo[-1].file_id)
                await update.message.reply_text(f"✅ Фото отправлено. С вашего счёта списано {COST_FOR_PHOTO} валюты.")
            else:
                await update.message.reply_text(f"❌ Недостаточно валюты для отправки фото. Стоимость: {COST_FOR_PHOTO}. Ваш баланс: {user_balance.get(user_id, 0)}.")
        elif update.message.video:
            await context.bot.send_video(partner, update.message.video.file_id)
        elif update.message.voice:
            await context.bot.send_voice(partner, update.message.voice.file_id)

# ====== КОМАНДА АДМИНА ======
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /admin.
    """
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        await show_admin_menu(update)
    else:
        await update.message.reply_text("🔐 Введите пароль:")
        context.user_data["awaiting_admin_password"] = True

async def show_admin_menu(update: Update):
    """
    Показывает админ-панель.
    """
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("💰 Выдать валюту", callback_data="admin_add_currency")],
        [InlineKeyboardButton("💸 Забрать валюту", callback_data="admin_remove_currency")],
        [InlineKeyboardButton("🚫 Завершить все чаты", callback_data="admin_stop_all")],
        [InlineKeyboardButton("👮‍♂️ Забанить", callback_data="admin_ban")],
        [InlineKeyboardButton("🔓 Разбанить", callback_data="admin_unban")],
        [InlineKeyboardButton("🚪 Выйти", callback_data="admin_exit")]
    ])
    await update.message.reply_text("🔐 Админ-панель", reply_markup=kb)

# ====== ЗАВЕРШЕНИЕ ЧАТА ======
async def end_chat(user_id, context):
    """
    Завершает чат для двух пользователей.
    """
    if user_id in active_chats:
        partner = active_chats.pop(user_id)
        active_chats.pop(partner, None)

        pair_key = tuple(sorted((user_id, partner)))
        if pair_key in show_name_requests:
            del show_name_requests[pair_key]

        task = active_tasks.pop(pair_key, None)
        if task:
            task.cancel()

        await context.bot.send_message(user_id, "❌ Чат завершён.", reply_markup=ReplyKeyboardRemove())
        await context.bot.send_message(partner, "❌ Собеседник вышел.", reply_markup=ReplyKeyboardRemove())
        
        if user_id in chat_history:
            del chat_history[user_id]
        if partner in chat_history:
            del chat_history[partner]

        await show_main_menu(user_id, context)
        await show_main_menu(partner, context)

# ====== ЗАПУСК БОТА ======
async def main():
    """
    Основная функция запуска бота.
    """
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.VOICE, media_handler))

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
