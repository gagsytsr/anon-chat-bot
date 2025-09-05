import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
DATABASE_URL = os.getenv("DATABASE_URL")

if not all([BOT_TOKEN, ADMIN_PASSWORD, DATABASE_URL]):
    raise ValueError("ОШИБКА: Одна или несколько переменных окружения не установлены! (BOT_TOKEN, ADMIN_PASSWORD, DATABASE_URL)")

# --- Константы бота ---
REWARD_FOR_REFERRAL = 10
COST_FOR_18PLUS = 50
COST_FOR_UNBAN = 50  # Изменено со 100 на 50
COST_FOR_PHOTO = 50
MAX_WARNINGS = 3
CHAT_TIMER_SECONDS = 60

ADMIN_IDS = set()

AVAILABLE_INTERESTS = {
    "Музыка": "🎵", "Игры": "🎮", "Кино": "🎬",
    "Путешествия": "✈️", "Общение": "💬", "18+": "🔞"
}
