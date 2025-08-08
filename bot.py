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
ADMIN_IDS = set()

if not BOT_TOKEN or not ADMIN_PASSWORD:
    logging.error("BOT_TOKEN или ADMIN_PASSWORD не установлены!")
    exit(1)

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

# Список интересов с эмодзи и ключами
available_interests = [
    ("🎵 Музыка", "music"),
    ("🎮 Игры", "games"),
    ("🎬 Кино", "movies"),
    ("✈️ Путешествия", "travel"),
    ("💬 Общение", "chat"),
    ("🔞 18+", "adult")
]

# Для поиска - вспомогательная функция фильтрации по интересам
def interests_match(int1, int2):
    # Если хотя бы один выбрал "другие интересы" (пусто) — совпадение всегда
    if not int1 or not int2:
        return True
    # Иначе пересечение должно быть не пустым
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
                await context.bot.send_message(referrer_id, "🎉 Новый пользователь по вашей ссылке!")
        except:
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

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

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
        display_interests = []
        for em_text, key in available_interests:
            if key in interests_list:
                display_interests.append(em_text)
        if not display_interests:
            display_interests = ["Другие интересы / Не выбраны"]
        await query.edit_message_text(
            f"✅ Ваши интересы: {', '.join(display_interests)}.\nИщем собеседника..."
        )
        # Запускаем поиск с учётом интересов
        if user_id not in waiting_users:
            waiting_users.append(user_id)
        await find_partner(context)
        return

    # Админка
    if data == "admin_stats":
        total_users = len([u for u in user_agreements if user_agreements[u]])
        active_pairs = len(active_chats) // 2
        await query.message.reply_text(
            f"📊 Пользователей: {total_users}\n💬 Активных чатов: {active_pairs}\n"
            f"⚠️ Жалоб: {len(reported_users)}\n⛔ Забанено: {len(banned_users)}\n"
            f"🔗 Рефералов: {sum(referrals.values())}"
        )
        return

    if data == "admin_stop_all":
        for uid in list(active_chats.keys()):
            await end_chat(uid, context)
        await query.message.reply_text("🚫 Все чаты завершены.")
        return

    if data == "admin_ban":
        await query.message.reply_text("Введите ID для бана:")
        context.user_data["awaiting_ban_id"] = True
        return

    if data == "admin_unban":
        await query.message.reply_text("Введите ID для разбана:")
        context.user_data["awaiting_unban_id"] = True
        return

    if data == "admin_exit":
        ADMIN_IDS.discard(user_id)
        await query.message.reply_text("🚪 Вы вышли из админ-панели.", reply_markup=ReplyKeyboardRemove())
        return

    # Кнопки из чата

    # Новый чат
    if data == "new_chat":
        await end_chat(user_id, context, notify_partner=True)
        # Удаляем из поиска на всякий случай
        if user_id in waiting_users:
            waiting_users.remove(user_id)
        await show_interests_menu(await context.bot.get_chat(user_id), user_id)
        return

    # Показывать ник (через 10 минут)
    if data.startswith("show_nick_"):
        partner = active_chats.get(user_id)
        if not partner:
            await query.message.reply_text("❌ Вы не в чате.")
            return
        answer = data.split("_")[-1]  # yes / no
        key = tuple(sorted((user_id, partner)))
        show_name_requests.setdefault(key, {user_id: None, partner: None})
        show_name_requests[key][user_id] = (answer == "yes")

        # Проверяем, согласны ли оба
        votes = show_name_requests[key]
        if None in votes.values():
            # Ждём второго
            await query.message.reply_text("✅ Ваш выбор принят, ждём ответа собеседника.")
        else:
            # Оба выбрали
            if all(votes.values()):
                # Оба согласны, отправляем ники
                user1, user2 = key
                try:
                    await context.bot.send_message(user1, f"👤 Ник вашего собеседника: @{(await context.bot.get_chat(user2)).username or 'нет ника'}")
                    await context.bot.send_message(user2, f"👤 Ник вашего собеседника: @{(await context.bot.get_chat(user1)).username or 'нет ника'}")
                except Exception as e:
                    logging.warning(f"Ошибка при отправке ника: {e}")
            else:
                # Кто-то отказался
                await context.bot.send_message(user_id, "❌ Обмен никами не состоялся.")
                partner_id = active_chats.get(user_id)
                if partner_id:
                    await context.bot.send_message(partner_id, "❌ Обмен никами не состоялся.")

            # Убираем запрос
            show_name_requests.pop(key, None)

        return

async def update_interests_menu(user_id, query):
    keyboard = []
    selected = user_interests.get(user_id, [])
    for em_text, key in available_interests:
        text = f"✅ {em_text}" if key in selected else em_text
        keyboard.append([InlineKeyboardButton(text, callback_data=f"interest_{key}")])
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

async def show_main_menu(user_id, context):
    keyboard = [["🔍 Поиск собеседника"], ["⚠️ Сообщить о проблеме"], ["🔗 Мои рефералы"]]
    await context.bot.send_message(user_id, "Выберите действие:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

async def show_interests_menu(update, user_id):
    keyboard = [[InlineKeyboardButton(em_text, callback_data=f"interest_{key}")] for em_text, key in available_interests]
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    user_interests[user_id] = []
    await update.message.reply_text("Выберите интересы:", reply_markup=InlineKeyboardMarkup(keyboard))

async def find_partner(context):
    # Перебираем waiting_users и пытаемся найти пару с пересекающимися интересами или если хоть один пустой
    i = 0
    while i < len(waiting_users):
        u1 = waiting_users[i]
        found = False
        for j in range(i+1, len(waiting_users)):
            u2 = waiting_users[j]
            i1 = user_interests.get(u1, [])
            i2 = user_interests.get(u2, [])
            if interests_match(i1, i2):
                # Нашли пару
                # Удаляем обоих из очереди
                waiting_users.remove(u2)
                waiting_users.remove(u1)
                # Связываем
                active_chats[u1] = u2
                active_chats[u2] = u1
                # Инициализируем show
