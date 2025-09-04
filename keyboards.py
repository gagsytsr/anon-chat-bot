from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

# --- Reply (обычные) клавиатуры ---

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Возвращает клавиатуру главного меню."""
    keyboard = [["🔍 Поиск собеседника"], ["💰 Мой баланс"], ["🔗 Мои рефералы"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_chat_keyboard() -> ReplyKeyboardMarkup:
    """Возвращает клавиатуру во время активного чата."""
    keyboard = [["🚫 Завершить чат"], ["🔍 Начать новый чат"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_reply_keyboard() -> ReplyKeyboardMarkup:
    """Возвращает постоянную клавиатуру для админ-панели."""
    keyboard = [
        ["📊 Статистика", "💰 Выдать валюту"],
        ["👮‍♂️ Забанить", "🔓 Разбанить"],
        ["💸 Забрать валюту", "🚫 Завершить все чаты"],
        ["⬅️ Выйти из админ-режима"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# --- Inline (кнопки в сообщении) клавиатуры ---

def get_agreement_keyboard() -> InlineKeyboardMarkup:
    """Возвращает кнопку согласия с правилами."""
    keyboard = [[InlineKeyboardButton("✅ Согласен", callback_data="agree")]]
    return InlineKeyboardMarkup(keyboard)

def get_interests_keyboard(user_interests: list, available_interests: dict) -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора интересов."""
    keyboard = []
    for interest, emoji in available_interests.items():
        text = f"✅ {interest} {emoji}" if interest in user_interests else f"{interest} {emoji}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"interest_{interest}")])
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    return InlineKeyboardMarkup(keyboard)

def get_unban_keyboard(cost: int) -> InlineKeyboardMarkup:
    """Клавиатура для запроса на разбан."""
    keyboard = [[InlineKeyboardButton(f"Разблокировать за {cost} валюты", callback_data="unban_request")]]
    return InlineKeyboardMarkup(keyboard)

def get_stop_all_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для подтверждения остановки всех чатов."""
    keyboard = [
        [InlineKeyboardButton("✅ Да, я уверен", callback_data="admin_confirm_stop_all")],
        [InlineKeyboardButton("❌ Отмена", callback_data="admin_cancel_stop_all")]
    ]
    return InlineKeyboardMarkup(keyboard)
