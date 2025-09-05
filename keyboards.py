from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from config import AVAILABLE_INTERESTS, COST_FOR_UNBAN

async def get_interests_keyboard(user_interests: list = None):
    current_interests = user_interests or []
    keyboard = []
    for interest, emoji in AVAILABLE_INTERESTS.items():
        text = f"✅ {interest} {emoji}" if interest in current_interests else f"{interest} {emoji}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"interest_{interest}")])
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    return InlineKeyboardMarkup(keyboard)

def get_main_menu_keyboard():
    keyboard = [["🔍 Поиск собеседника"], ["💰 Мой баланс"], ["🔗 Мои рефералы"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

def get_admin_reply_keyboard():
    keyboard = [
        ["🔐 Админ-панель"],
        ["🔍 Поиск собеседника", "💰 Мой баланс"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_chat_keyboard():
    keyboard = [["🚫 Завершить чат"], ["🔍 Начать новый чат"], ["⚠️ Пожаловаться"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_ban_keyboard():
    keyboard = [[InlineKeyboardButton(f"Разблокировать за {COST_FOR_UNBAN} монет", callback_data="unban_request")]]
    return InlineKeyboardMarkup(keyboard)
    
def get_balance_keyboard():
    keyboard = [
        [InlineKeyboardButton("💳 Заработать", callback_data="earn_coins")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_keyboard():
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]]
    return InlineKeyboardMarkup(keyboard)

def get_name_exchange_keyboard():
    keyboard = [
        [InlineKeyboardButton("✅ Да, показать ник", callback_data="exchange_yes")],
        [InlineKeyboardButton("❌ Нет, спасибо", callback_data="exchange_no")]
    ]
    return InlineKeyboardMarkup(keyboard)
    
def get_report_keyboard():
    """Клавиатура для выбора причины жалобы."""
    keyboard = [
        [InlineKeyboardButton("Оскорбления", callback_data="report_insult")],
        [InlineKeyboardButton("Спам", callback_data="report_spam")],
        [InlineKeyboardButton("Неприемлемый контент", callback_data="report_content")],
        [InlineKeyboardButton("Отмена", callback_data="report_cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("💰 Выдать валюту", callback_data="admin_add_currency")],
        [InlineKeyboardButton("💸 Забрать валюту", callback_data="admin_remove_currency")],
        [InlineKeyboardButton("🚫 Завершить все чаты", callback_data="admin_stop_all")],
        [InlineKeyboardButton("👮‍♂️ Забанить", callback_data="admin_ban")],
        [InlineKeyboardButton("🔓 Разбанить", callback_data="admin_unban")],
    ]
    return InlineKeyboardMarkup(keyboard)

def remove_keyboard():
    return ReplyKeyboardRemove()
