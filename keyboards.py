from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

# ===== КОНСТАНТЫ (можно вынести в отдельный config.py) =====
COST_FOR_UNBAN = 100

# Обновленный список интересов с эмодзи
available_interests = {
    "Музыка": "🎵", "Игры": "🎮", "Кино": "🎬",
    "Путешествия": "✈️", "Общение": "💬", "18+": "🔞"
}

def get_start_keyboard():
    """
    Клавиатура для команды /start с кнопкой согласия.
    """
    keyboard = [[InlineKeyboardButton("✅ Согласен", callback_data="agree")]]
    return InlineKeyboardMarkup(keyboard)

def get_main_menu_keyboard(is_admin: bool = False):
    """
    Создает основную клавиатуру. Добавляет кнопку админа, если пользователь - админ.
    """
    keyboard = [
        ["🔍 Поиск собеседника"],
        ["💰 Мой баланс", "🔗 Мои рефералы"]
    ]
    if is_admin:
        keyboard.append(["👑 Админ-панель"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_chat_keyboard():
    """
    Клавиатура во время активного чата.
    """
    return ReplyKeyboardMarkup(
        [["🚫 Завершить чат"], ["🔍 Начать новый чат"], ["⚠️ Пожаловаться"]],
        resize_keyboard=True
    )

def get_unban_keyboard():
    """
    Клавиатура для забаненного пользователя.
    """
    keyboard = [[InlineKeyboardButton(f"Разблокировать за {COST_FOR_UNBAN} валюты", callback_data="unban_request")]]
    return InlineKeyboardMarkup(keyboard)

def get_interests_keyboard(selected_interests=None):
    """
    Создает клавиатуру для выбора интересов.
    """
    if selected_interests is None:
        selected_interests = []
        
    keyboard = []
    for interest, emoji in available_interests.items():
        text = f"✅ {interest} {emoji}" if interest in selected_interests else f"{interest} {emoji}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"interest_{interest}")])
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    return InlineKeyboardMarkup(keyboard)

def get_show_name_keyboard():
    """
    Клавиатура с предложением показать ник.
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, показать ник", callback_data="show_name_yes")],
        [InlineKeyboardButton("❌ Нет, не показывать", callback_data="show_name_no")]
    ])
    
def get_report_keyboard():
    """
    Клавиатура для выбора причины жалобы.
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Не по теме комнаты", callback_data="report_reason_off_topic")],
        [InlineKeyboardButton("Оскорбления", callback_data="report_reason_insult")],
        [InlineKeyboardButton("Неприемлемый контент", callback_data="report_reason_content")],
        [InlineKeyboardButton("Разглашение личной информации", callback_data="report_reason_private_info")]
    ])

def get_admin_keyboard():
    """
    Клавиатура админ-панели.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("💰 Выдать валюту", callback_data="admin_add_currency")],
        [InlineKeyboardButton("💸 Забрать валюту", callback_data="admin_remove_currency")],
        [InlineKeyboardButton("🚫 Завершить все чаты", callback_data="admin_stop_all")],
        [InlineKeyboardButton("👮‍♂️ Забанить", callback_data="admin_ban")],
        [InlineKeyboardButton("🔓 Разбанить", callback_data="admin_unban")],
        [InlineKeyboardButton("🚪 Выйти из админки (временно)", callback_data="admin_exit_temp")]
    ])
