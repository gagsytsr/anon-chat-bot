import asyncio
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
import logging

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TOKEN = "YOUR_BOT_TOKEN_HERE"
ADMIN_IDS = {123456789}  # ID админов для управления валютой

# Данные о пользователях
user_balances = {}  # user_id -> int (валюта)
user_referrals = {}  # user_id -> кто пригласил user_id
user_interests = {}  # user_id -> список интересов
waiting_users = []  # пользователи в поиске
active_chats = {}  # user_id -> собеседник user_id
chat_start_times = {}  # user_id -> время старта чата
nick_shown = set()  # кто уже показал ник
nick_request_tasks = {}  # user_id -> asyncio.Task для показа кнопок

# Интересы и стоимость комнаты
available_interests = {
    "🎵 Музыка": 0,
    "🎮 Игры": 0,
    "🎬 Кино": 0,
    "✈️ Путешествия": 0,
    "💬 Общение": 0,
    "🔞 18+": 50,
}

OTHER_INTERESTS_KEY = "Другие интересы"

# ==================== КОМАНДЫ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Если новый пользователь — даем баланс 0 и проверяем реферала
    if user_id not in user_balances:
        user_balances[user_id] = 0
        # Пытаемся считать реферала из параметров ссылки /start ref123456
        if context.args:
            ref_id_str = context.args[0]
            if ref_id_str.startswith("ref"):
                try:
                    ref_id = int(ref_id_str[3:])
                    if ref_id != user_id:
                        user_referrals[user_id] = ref_id
                        user_balances[ref_id] = user_balances.get(ref_id, 0) + 10
                        await context.bot.send_message(ref_id, f"🎉 Вам начислено 10 монет за приглашённого!")
                except Exception:
                    pass

    user_interests[user_id] = []
    await update.message.reply_text(
        "Привет! Выбери свои интересы для комнаты.\n"
        "⚠️ ВНИМАНИЕ: общение строго по выбранной теме. Нарушение — бан.\n"
        "🔞 Комната 18+ стоит 50 монет, остальные комнаты бесплатные.\n"
        "Если ничего не выберешь — попадёшь в случайную комнату.\n"
        "Для выбора нажми кнопки ниже.",
    )
    await show_interests_menu(user_id, context)

async def show_interests_menu(user_id, context):
    keyboard = []
    for interest, price in available_interests.items():
        keyboard.append([InlineKeyboardButton(f"{interest} {'(50 монет)' if price else '(бесплатно)'}", callback_data=f"interest_{interest}")])
    keyboard.append([InlineKeyboardButton(OTHER_INTERESTS_KEY, callback_data=f"interest_{OTHER_INTERESTS_KEY}")])
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    await context.bot.send_message(user_id, "Выберите интересы (можно несколько):", reply_markup=InlineKeyboardMarkup(keyboard))

async def interests_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data.startswith("interest_"):
        interest = data[9:]
        if interest == OTHER_INTERESTS_KEY:
            user_interests[user_id] = [OTHER_INTERESTS_KEY]
            await query.answer(f"Вы выбрали: {OTHER_INTERESTS_KEY}")
        else:
            if interest in user_interests.get(user_id, []):
                user_interests[user_id].remove(interest)
                await query.answer(f"Удалён интерес: {interest}")
            else:
                # Если выбрали другие интересы — очищаем остальные
                if OTHER_INTERESTS_KEY in user_interests.get(user_id, []):
                    user_interests[user_id] = []
                user_interests.setdefault(user_id, []).append(interest)
                await query.answer(f"Добавлен интерес: {interest}")
        # Обновим меню с выделением
        await update.callback_query.edit_message_reply_markup(reply_markup=await build_interests_keyboard(user_id))
    elif data == "interests_done":
        # Если ничего не выбрали — ставим другие интересы
        if not user_interests.get(user_id):
            user_interests[user_id] = [OTHER_INTERESTS_KEY]
        await query.answer("Выбор сохранён")
        await query.edit_message_text("Выбор интересов сохранён.\nДля поиска собеседника нажмите /find")

async def build_interests_keyboard(user_id):
    keyboard = []
    selected = user_interests.get(user_id, [])
    for interest, price in available_interests.items():
        text = f"{interest} {'(50 монет)' if price else '(бесплатно)'}"
        if interest in selected:
            text = "✅ " + text
        keyboard.append([InlineKeyboardButton(text, callback_data=f"interest_{interest}")])
    other_text = OTHER_INTERESTS_KEY
    if OTHER_INTERESTS_KEY in selected:
        other_text = "✅ " + other_text
    keyboard.append([InlineKeyboardButton(other_text, callback_data=f"interest_{OTHER_INTERESTS_KEY}")])
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    return InlineKeyboardMarkup(keyboard)

# ==================== ПОИСК СОБЕСЕДНИКА ====================

async def find(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in active_chats:
        await update.message.reply_text("Вы уже в чате, сначала завершите текущий (/stop)")
        return

    if user_id not in user_interests or not user_interests[user_id]:
        user_interests[user_id] = [OTHER_INTERESTS_KEY]

    if user_id not in waiting_users:
        waiting_users.append(user_id)

    await update.message.reply_text("Идёт поиск собеседника...")

    await try_to_pair(context)

async def try_to_pair(context: ContextTypes.DEFAULT_TYPE):
    paired = set()
    for i in range(len(waiting_users)):
        if waiting_users[i] in paired:
            continue
        user1 = waiting_users[i]
        interests1 = user_interests.get(user1, [OTHER_INTERESTS_KEY])
        if not interests1:
            interests1 = [OTHER_INTERESTS_KEY]
        for j in range(i + 1, len(waiting_users)):
            if waiting_users[j] in paired:
                continue
            user2 = waiting_users[j]
            interests2 = user_interests.get(user2, [OTHER_INTERESTS_KEY])
            if not interests2:
                interests2 = [OTHER_INTERESTS_KEY]

            # Проверка на совпадение интересов (или "Другие интересы")
            common = set(interests1).intersection(set(interests2))
            if not common:
                continue

            # Проверка оплаты 18+
            if "🔞 18+" in common:
                if user_balances.get(user1, 0) < 50 or user_balances.get(user2, 0) < 50:
                    # Кто-то не может оплатить
                    continue

            # Если здесь — пара найдена
            # Списываем монеты за 18+, если нужно
            if "🔞 18+" in common:
                user_balances[user1] -= 50
                user_balances[user2] -= 50
                await context.bot.send_message(user1, "💳 Списание 50 монет за доступ в 18+ комнату.")
                await context.bot.send_message(user2, "💳 Списание 50 монет за доступ в 18+ комнату.")

            # Запускаем чат
            active_chats[user1] = user2
            active_chats[user2] = user1
            paired.update({user1, user2})
            waiting_users.remove(user1)
            waiting_users.remove(user2)
            chat_start_times[user1] = asyncio.get_event_loop().time()
            chat_start_times[user2] = chat_start_times[user1]

            # Начальное сообщение с предупреждением о теме чата
            await context.bot.send_message(user1,
                f"🎯 Собеседник найден! Тема чата: {', '.join(common)}\n"
                "⚠️ Общайтесь строго по теме, иначе — бан.\n"
                "У вас есть 10 минут, потом появится выбор — показывать ли ник.")
            await context.bot.send_message(user2,
                f"🎯 Собеседник найден! Тема чата: {', '.join(common)}\n"
                "⚠️ Общайтесь строго по теме, иначе — бан.\n"
                "У вас есть 10 минут, потом появится выбор — показывать ли ник.")

            # Запускаем таймер на 10 минут и появление кнопок обмена никами
            context.application.create_task(timer_show_nick_buttons(user1, user2, context))
            return

# ==================== ТАЙМЕР И КНОПКИ НИКА ====================

async def timer_show_nick_buttons(user1, user2, context):
    await asyncio.sleep(600)  # 10 минут
    keyboard = [
        [
            InlineKeyboardButton("Да", callback_data="show_nick_yes"),
            InlineKeyboardButton("Нет", callback_data="show_nick_no"),
        ]
    ]
    for user_id in (user1, user2):
        try:
            await context.bot.send_message(user_id, "10 минут прошло. Вы хотите показывать свой ник?", reply_markup=InlineKeyboardMarkup(keyboard))
        except:
            pass

# Обработка кнопок показа ника
async def nick_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if user_id not in active_chats:
        await query.answer("Вы не в чате")
        return

    partner_id = active_chats[user_id]

    # Запоминаем выбор пользователя
    if data == "show_nick_yes":
        nick_shown.add(user_id)
        await query.answer("Вы выбрали показывать ник")
    elif data == "show_nick_no":
        nick_shown.discard(user_id)
        await query.answer("Вы выбрали не показывать ник")
    else:
        await query.answer()
        return

    # Проверяем, ответил ли уже второй
    if partner_id in nick_shown or partner_id not in active_chats:
        # Оба ответили
        if user_id in nick_shown and partner_id in nick_shown:
            # Отправляем ники друг другу
            user_nick = (await context.bot.get_chat(user_id)).username or "(ник не задан)"
            partner_nick = (await context.bot.get_chat(partner_id)).username or "(ник не задан)"
            await context.bot.send_message(user_id, f"Ник собеседника: @{partner_nick}")
            await context.bot.send_message(partner_id, f"Ник собеседника: @{user_nick}")
        else:
            # Кто-то отказался показывать
            await context.bot.send_message(user_id, "Обмен никами не состоялся.")
            await context.bot.send_message(partner_id, "Обмен никами не состоялся.")

# ==================== ОБРАБОТКА СООБЩЕНИЙ В ЧАТЕ ====================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in active_chats:
        await update.message.reply_text("Вы не в чате. Для поиска собеседника — /find")
        return
    partner_id = active_chats[user_id]

    # Проверка на соблюдение темы чата
    user_topics = set(user_interests.get(user_id, [OTHER_INTERESTS_KEY]))
    partner_topics = set(user_interests.get(partner_id, [OTHER_INTERESTS_KEY]))
    common_topics = user_topics.intersection(partner_topics)
    # Если "Другие интересы" — тема не ограничена
    if OTHER_INTERESTS_KEY not in common_topics:
        # Для упрощения: если сообщение содержит ключевые слова из темы (можно расширить)
        text = update.message.text.lower()
        # Например, если тема "Музыка" — в тексте должно быть слово "музыка" или "песня" и т.п.
        # Здесь сделаем простую проверку — если в тексте нет названия интереса (маловероятно идеальное)
        if not any(topic.lower().strip("🎵🎮🎬✈️💬🔞 ") in text for topic in common_topics):
            await update.message.reply_text("⚠️ Нарушение темы чата — вы забанены.")
            await stop_chat(user_id, context, banned=True)
            return

    # Пересылаем сообщение собеседнику
    try:
        await context.bot.send_message(partner_id, f"👤 Собеседник: {update.message.text}")
    except:
        await update.message.reply_text("Ошибка при отправке сообщения собеседнику.")

# ==================== КОМАНДА ЗАВЕРШЕНИЯ ЧАТА ====================

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await stop_chat(user_id, context)

async def stop_chat(user_id, context, banned=False):
    if user_id not in active_chats:
        await context.bot.send_message(user_id, "Вы не в чате.")
        return
    partner_id = active_chats.pop(user_id)
    active_chats.pop(partner_id, None)
    chat_start_times.pop(user_id, None)
    chat_start_times.pop(partner_id, None)
    nick_shown.discard(user_id)
    nick_shown.discard(partner_id)
    if user_id in waiting_users:
        waiting_users.remove(user_id)
    if partner_id in waiting_users:
        waiting_users.remove(partner_id)

    if banned:
        await context.bot.send_message(user_id, "Вы были забанены за нарушение правил.")
    else:
        await context.bot.send_message(user_id, "Чат завершён.")
    try:
        await context.bot.send_message(partner_id, "Собеседник завершил чат.")
    except:
        pass

# ==================== КНОПКА "НАЧАТЬ НОВЫЙ ЧАТ" ====================

async def new_chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await stop_chat(user_id, context)
    if user_id not in waiting_users:
        waiting_users.append(user_id)
    await query.answer("Поиск нового собеседника запущен.")
    await try_to_pair(context)

# ==================== АДМИН КОМАНДЫ ====================

async def admin_add_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("Нет доступа")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /addmoney <user_id> <amount>")
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
        user_balances[target_id] = user_balances.get(target_id, 0) + amount
        await update.message.reply_text(f"Добавлено {amount} монет пользователю {target_id}")
    except Exception:
        await update.message.reply_text("Ошибка в аргументах")

async def admin_remove_money(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("Нет доступа")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /removemoney <user_id> <amount>")
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
        current = user_balances.get(target_id, 0)
        user_balances[target_id] = max(0, current - amount)
        await update.message.reply_text(f"Снято {amount} монет с пользователя {target_id}")
    except Exception:
        await update.message.reply_text("Ошибка в аргументах")

# ==================== ЗАПУСК БОТА ====================

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("find", find))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CallbackQueryHandler(interests_callback, pattern=r"^interest_"))
    app.add_handler(CallbackQueryHandler(interests_callback, pattern="interests_done"))
    app.add_handler(CallbackQueryHandler(nick_button_handler, pattern=r"^show_nick_"))
    app.add_handler(CallbackQueryHandler(new_chat_callback, pattern="new_chat"))
    app.add_handler(CommandHandler("addmoney", admin_add_money))
    app.add_handler(CommandHandler("removemoney", admin_remove_money))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущен...")
    app.run_polling()

if __name__ == '__main__':
    main()
