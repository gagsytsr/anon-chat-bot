# keyboards.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

# --- Reply (обычные) клавиатуры ---

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Возвращает клавиатуру главного меню."""
    keyboard = [["🔍 Поиск собеседника"], ["💰 Мой баланс"], ["🔗 Мои рефералы"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_chat_keyboard() -> ReplyKeyboardMarkup:
    """Возвращает клавиатуру во время активного чата."""
    keyboard = [["🚫 Завершить чат"], ["🔍 Начать новый чат"], ["⚠️ Пожаловаться"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- Inline (кнопки в сообщении) клавиатуры ---

def get_agreement_keyboard() -> InlineKeyboardMarkup:
    """Возвращает кнопку согласия с правилами."""
    keyboard = [[InlineKeyboardButton("✅ Согласен", callback_data="agree")]]
    return InlineKeyboardMarkup(keyboard)

async def get_interests_keyboard(user_id: int, user_interests: dict, available_interests: dict) -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора интересов."""
    keyboard = []
    selected = user_interests.get(user_id, [])
    for interest, emoji in available_interests.items():
        text = f"✅ {interest} {emoji}" if interest in selected else f"{interest} {emoji}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"interest_{interest}")])
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    return InlineKeyboardMarkup(keyboard)

def get_show_name_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с предложением показать ник."""
    keyboard = [
        [InlineKeyboardButton("✅ Да, показать ник", callback_data="show_name_yes")],
        [InlineKeyboardButton("❌ Нет, не показывать", callback_data="show_name_no")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_report_reasons_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с причинами жалобы."""
    keyboard = [
        [InlineKeyboardButton("Не по теме комнаты", callback_data="report_reason_off_topic")],
        [InlineKeyboardButton("Оскорбления", callback_data="report_reason_insult")],
        [InlineKeyboardButton("Неприемлемый контент", callback_data="report_reason_content")],
        [InlineKeyboardButton("Разглашение личной информации", callback_data="report_reason_private_info")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_unban_keyboard(cost: int) -> InlineKeyboardMarkup:
    """Клавиатура для запроса на разбан."""
    keyboard = [[InlineKeyboardButton(f"Разблокировать за {cost} валюты", callback_data="unban_request")]]
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура админ-панели."""
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

