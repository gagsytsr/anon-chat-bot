from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

# --- Reply (обычные) клавиатуры ---

def get_main_menu_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Возвращает клавиатуру главного меню. Добавляет кнопку админа, если нужно."""
    keyboard = [
        ["🔍 Поиск собеседника"],
        ["💰 Мой баланс", "🔗 Мои рефералы"]
    ]
    if is_admin:
        keyboard.append(["👑 Админ-панель"]) # Новая кнопка для админов
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_chat_keyboard() -> ReplyKeyboardMarkup:
    """Возвращает клавиатуру во время активного чата."""
    keyboard = [["🚫 Завершить чат"], ["🔍 Начать новый чат"], ["⚠️ Пожаловаться"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- Inline (кнопки в сообщении) клавиатуры ---
# Остальные клавиатуры остаются без изменений...
def get_agreement_keyboard() -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton("✅ Согласен", callback_data="agree")]]
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура админ-панели."""
    keyboard = [
        [InlineKeyboardButton("💰 Выдать валюту", callback_data="admin_add_currency")],
        [InlineKeyboardButton("💸 Забрать валюту", callback_data="admin_remove_currency")],
        [InlineKeyboardButton("🚫 Завершить все чаты", callback_data="admin_stop_all_chats")],
        [InlineKeyboardButton("👮‍♂️ Забанить", callback_data="admin_ban")],
        [InlineKeyboardButton("🔓 Разбанить", callback_data="admin_unban")],
        [InlineKeyboardButton("🚪 Выйти", callback_data="admin_exit")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ... скопируйте сюда остальные ваши inline-клавиатуры из старого файла ...
def get_unban_keyboard(cost: int) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(f"Разблокировать за {cost} валюты", callback_data="unban_request")]]
    return InlineKeyboardMarkup(keyboard)
