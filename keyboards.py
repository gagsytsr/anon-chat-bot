# keyboards.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from config import AVAILABLE_INTERESTS, COST_FOR_UNBAN

async def get_interests_keyboard(user_interests: list = None):
    """Создает клавиатуру для выбора интересов."""
    if user_interests is None:
        user_interests = []
        
    keyboard = []
    for interest, emoji in AVAILABLE_INTERESTS.items():
        text = f"✅ {interest} {emoji}" if interest in user_interests else f"{interest} {emoji}"
        keyboard.append([InlineKeyboardButton(text, callback_data=f"interest_{interest}")])
    keyboard.append([InlineKeyboardButton("➡️ Готово", callback_data="interests_done")])
    return InlineKeyboardMarkup(keyboard)

def get_main_menu_keyboard():
    """Возвращает главную клавиатуру."""
    keyboard = [["🔍 Поиск собеседника"], ["💰 Мой баланс"], ["🔗 Мои рефералы"]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_chat_keyboard():
    """Возвращает клавиатуру для активного чата."""
    markup = ReplyKeyboardMarkup(
        [["🚫 Завершить чат"], ["🔍 Начать новый чат"], ["⚠️ Пожаловаться"]],
        resize_keyboard=True
    )
    return markup
    
def get_ban_keyboard():
    """Клавиатура для забаненного пользователя."""
    keyboard = [[InlineKeyboardButton(f"Разблокировать за {COST_FOR_UNBAN} валюты", callback_data="unban_request")]]
    return InlineKeyboardMarkup(keyboard)

def get_show_name_keyboard():
    """Клавиатура для предложения обмена никами."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, показать ник", callback_data="show_name_yes")],
        [InlineKeyboardButton("❌ Нет, не показывать", callback_data="show_name_no")]
    ])
    return keyboard

def get_report_keyboard():
    """Клавиатура для выбора причины жалобы."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Не по теме комнаты", callback_data="report_reason_off_topic")],
        [InlineKeyboardButton("Оскорбления", callback_data="report_reason_insult")],
        [InlineKeyboardButton("Неприемлемый контент", callback_data="report_reason_content")],
        [InlineKeyboardButton("Разглашение личной информации", callback_data="report_reason_private_info")]
    ])
    return keyboard

def get_admin_keyboard():
    """Клавиатура админ-панели."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("💰 Выдать валюту", callback_data="admin_add_currency")],
        [InlineKeyboardButton("💸 Забрать валюту", callback_data="admin_remove_currency")],
        [InlineKeyboardButton("🚫 Завершить все чаты", callback_data="admin_stop_all")],
        [InlineKeyboardButton("👮‍♂️ Забанить", callback_data="admin_ban")],
        [InlineKeyboardButton("🔓 Разбанить", callback_data="admin_unban")],
        [InlineKeyboardButton("🚪 Выйти", callback_data="admin_exit")]
    ])
    return kb
