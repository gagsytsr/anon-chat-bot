import asyncio
import logging
import os
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
if not BOT_TOKEN or not ADMIN_PASSWORD:
    logging.error("BOT_TOKEN или ADMIN_PASSWORD не установлены!")
    exit(1)

# Админские user_id — впиши сюда свои ID
ADMIN_IDS = {123456789, 987654321}

waiting_users = []  # список юзеров в поиске
active_chats = {}  # {user_id: partner_id}
show_name_requests = {}  # {(user1,user2): {user1: None/True/False, user2: None/True/False}}
user_agreements = {}
banned_users = set()
reported_users = {}
user_interests = {}
search_timeouts = {}
referrals = {}
invited_by = {}

# Валюта пользователей
user_currency = {}

# Список интересов с эмодзи и ключами
available_interests = [
    ("🎵 Музыка", "music"),
    ("🎮 Игры", "games"),
    ("🎬 Кино", "movies"),
    ("✈️ Путешествия", "travel"),
    ("💬 Общение", "chat"),
    ("🔞 18+", "adult")
]

def is_admin(user_id):
    return user_id in ADMIN_IDS

def interests_match(int1, int2):
    # Если хотя бы один пустой — считаем совпадение
    if not int1 or not int2:
        return True
    return bool(set(int1) & set(int2))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in banned_users:
        await update.message.reply_text("❌ Вы заблокированы.")
        return

    # Реферальная система
    if context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user_id and user_id not in invited_by:
                referrals[referrer_id] = referrals.get(referrer_id, 0) + 1
                invited_by[user_id] = referrer_id
                # Начисляем 10 валюты за приглашение
                user_currency[referrer_id] = user_currency.get(referrer_id, 0) + 10
                await context.bot.send_message(referrer_id, "🎉 Новый пользователь по вашей ссылке! +10 монет")
        except Exception:
            pass

    user_agreements[user_id] = False
    keyboard = [[InlineKeyboardButton("✅ Согласен", callback_data="agree")]]
    await update.message.reply_text(
        "👋 Добро пожаловать в анонимный чат!\n\n"
        "⚠️ Внимание:\n"
        "• Запрещено нарушать законы.\n"
        "• Соблюдайте уважение.\n"
        "• Общение должно быть строго по теме комнаты — иначе бан.\n\n"
        "Нажмите 'Согласен' чтобы начать.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if user_id in banned_users:
        await query.message.reply_text("❌ Вы заблокированы и не можете использовать бота.")
        return

    # Согласие с правилами
    if data == "agree":
        user_agreements[user_id] = True
        await show_main_menu(user_id, context)
        return

    # Обработка выбора интересов
    if data.startswith("interest_"):
        interest_key = data.replace("interest_", "")
        current = user_interests.get(user_id, [])
        if interest_key in current:
            current.remove(interest_key)
        else:
            current.append(interest_key)
        user_interests[user_id] = current
        await update_interests_menu(user_id, query)
        return

    if data == "interests_done":
        interests_list = user_interests.get(user_id, [])
        # Проверка на 18+ и хватает ли валюты
        if "adult" in interests_list:
            coins = user_currency.get(user_id, 0)
            if coins < 50:
                await query.edit_message_text(
                    f"Для доступа к комнате 🔞 18+ требуется 50 монет.\n"
                    f"У вас {coins} монет.\n"
                    f"Приглашайте друзей, чтобы заработать монеты!"
                )
                return
            else:
                user_currency[user_id] = coins - 50
                await context.bot.send_message(user_id, "✅ Списано 50 монет за доступ к комнате 18+.")
        display_interests = []
        for em_text, key in available_interests:
            if key in interests_list:
                display_interests.append(em_text)
        if not display_interests:
            display_interests = ["Другие интересы / Не выбраны"]
        await query.edit_message_text(
            f"✅ Ваши интересы: {', '.join(display_interests)}.\nИщем собеседника..."
        )
        if user_id not in waiting_users:
            waiting_users.append(user_id)
        await find_partner(context)
        return

    # Админка и другие кнопки можно добавить ниже...

    if data == "new_chat":
        await end_chat(user_id, context, notify_partner=True)
        if user_id in waiting_users:
            waiting_users.remove(user_id)
        # Заново показать меню интересов
        chat = await context.bot.get_chat(user_id)
        await show_interests_menu(chat, user_id)
        return

    # Логика обмена никами и др. - не трогаем, если надо - добавлю

async def update_interests_menu(user_id, query):
    keyboard = []
    selected = user_interests.get(user_id, [])
    for em_text, key in available_interests:
        text = f"✅ {em_text}" if key in selected else em_text
        keyboard.append([InlineKeyboardButton(text, callback_data=f"interest_{key}")])
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

async def show_main_menu(user_id, context):
    coins = user_currency.get(user_id, 0)
    keyboard = [["🔍 Поиск собеседника"], ["⚠️ Сообщить о проблеме"], ["🔗 Мои рефералы"], [f"💰 Баланс: {coins} монет"]]
    await context.bot.send_message(user_id, "Выберите действие:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

async def show_interests_menu(update, user_id):
    keyboard = [[InlineKeyboardButton(em_text, callback_data=f"interest_{key}")] for em_text, key in available_interests]
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    user_interests[user_id] = []
    await update.message.reply_text("Выберите интересы:", reply_markup=InlineKeyboardMarkup(keyboard))

async def find_partner(context):
    i = 0
    while i < len(waiting_users):
        u1 = waiting_users[i]
        found = False
        for j in range(i+1, len(waiting_users)):
            u2 = waiting_users[j]
            i1 = user_interests.get(u1, [])
            i2 = user_interests.get(u2, [])
            if interests_match(i1, i2):
                # Убедимся, что оба не забанены
                if u1 in banned_users or u2 in banned_users:
                    continue
                waiting_users.remove(u2)
                waiting_users.remove(u1)
                active_chats[u1] = u2
                active_chats[u2] = u1
                await context.bot.send_message(u1, "💬 Вы подключены к собеседнику, общайтесь по теме!")
                await context.bot.send_message(u2, "💬 Вы подключены к собеседнику, общайтесь по теме!")
                found = True
                break
        if not found:
            i += 1

async def end_chat(user_id, context, notify_partner=False):
    partner = active_chats.pop(user_id, None)
    if partner:
        active_chats.pop(partner, None)
        if notify_partner:
            try:
                await context.bot.send_message(partner, "🚫 Ваш собеседник покинул чат.")
            except Exception:
                pass

# ---------------- Админские команды ----------------

async def addcoins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return
    if len(context.args) != 2:
        await update.message.reply_text("Использование: /addcoins <user_id> <amount>")
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❗️ Неверный формат user_id или amount.")
        return
    user_currency[target_id] = user_currency.get(target_id, 0) + amount
    await update.message.reply_text(f"✅ Выдано {amount} монет пользователю {target_id}.")

async def removecoins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return
    if len(context.args) != 2:
        await update.message.reply_text("Использование: /removecoins <user_id> <amount>")
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❗️ Неверный формат user_id или amount.")
        return
    current = user_currency.get(target_id,
