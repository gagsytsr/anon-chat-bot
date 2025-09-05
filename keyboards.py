# keyboards.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from config import AVAILABLE_INTERESTS, COST_FOR_UNBAN

async def get_interests_keyboard(user_interests: list = None):
    """Создает клавиатуру для выбора интересов."""
    current_interests = user_interests or []
    keyboard = []
    for interest, emoji in AVAILABLE_INTERESTS.items():
        text = f"✅ {interest} {emoji}" if interest in current_interests else f"{interest} {emoji}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"interest_{interest}")])
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    return InlineKeyboardMarkup(keyboard)

def get_main_menu_keyboard():
    """Возвращает главную клавиатуру (ReplyKeyboardMarkup)."""
    keyboard = [["🔍 Поиск собеседника"], ["💰 Мой баланс"], ["🔗 Мои рефералы"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

def get_chat_keyboard():
    """Возвращает клавиатуру для активного чата."""
    keyboard = [["🚫 Завершить чат"], ["🔍 Начать новый чат"], ["⚠️ Пожаловаться"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_ban_keyboard():
    """Клавиатура для забаненного пользователя (Inline)."""
    keyboard = [[InlineKeyboardButton(f"Разблокировать за {COST_FOR_UNBAN} валюты", callback_data="unban_request")]]
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard():
    """Клавиатура админ-панели (Inline)."""
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("💰 Выдать валюту", callback_data="admin_add_currency")],
        [InlineKeyboardButton("💸 Забрать валюту", callback_data="admin_remove_currency")],
        [InlineKeyboardButton("🚫 Завершить все чаты", callback_data="admin_stop_all")],
        [InlineKeyboardButton("👮‍♂️ Забанить", callback_data="admin_ban")],
        [InlineKeyboardButton("🔓 Разбанить", callback_data="admin_unban")],
        [InlineKeyboardButton("🚪 Выйти", callback_data="admin_exit")]
    ]
    return InlineKeyboardMarkup(keyboard)

def remove_keyboard():
    """Возвращает объект для удаления Reply-клавиатуры."""
    return ReplyKeyboardRemove()
