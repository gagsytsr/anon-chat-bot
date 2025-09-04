from telegram import InlineKeyboardMarkup, InlineKeyboardButton

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("💰 Начислить валюту", callback_data="admin_add_currency")],
        [InlineKeyboardButton("💸 Забрать валюту", callback_data="admin_remove_currency")],
        [InlineKeyboardButton("👮‍♂️ Забанить", callback_data="admin_ban")],
        [InlineKeyboardButton("🔓 Разбанить", callback_data="admin_unban")],
        [InlineKeyboardButton("🚪 Выйти", callback_data="admin_exit")]
    ])
from telegram import ReplyKeyboardMarkup

def main_menu():
    return ReplyKeyboardMarkup(
        [["🔍 Поиск", "🔗 Рефералы"], ["💰 Баланс"]],
        resize_keyboard=True
    )
