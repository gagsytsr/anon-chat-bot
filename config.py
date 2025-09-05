# config.py
import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла для локальной разработки
load_dotenv()

# Обязательные переменные
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
DATABASE_URL = os.getenv("DATABASE_URL")

if not all([BOT_TOKEN, ADMIN_PASSWORD, DATABASE_URL]):
    raise ValueError("Одна или несколько переменных окружения (BOT_TOKEN, ADMIN_PASSWORD, DATABASE_URL) не установлены!")

# Константы (можно вынести сюда для удобства)
REWARD_FOR_REFERRAL = 10
COST_FOR_18PLUS = 50
COST_FOR_UNBAN = 100
COST_FOR_PHOTO = 50
MAX_WARNINGS = 3

# Список ID админов, которые вошли в систему (остается в памяти)
ADMIN_IDS = set()

# Доступные интересы
AVAILABLE_INTERESTS = {
    "Музыка": "🎵", "Игры": "🎮", "Кино": "🎬",
    "Путешествия": "✈️", "Общение": "💬", "18+": "🔞"
}
