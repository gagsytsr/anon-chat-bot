# config.py
import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла для локальной разработки
load_dotenv()

# Обязательные переменные из окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
DATABASE_URL = os.getenv("DATABASE_URL")

# Эта проверка остановит запуск, если одна из переменных не найдена
if not all([BOT_TOKEN, ADMIN_PASSWORD, DATABASE_URL]):
    raise ValueError("ОШИБКА: Одна или несколько переменных окружения не установлены! (BOT_TOKEN, ADMIN_PASSWORD, DATABASE_URL)")

# --- Константы бота ---
REWARD_FOR_REFERRAL = 10
COST_FOR_18PLUS = 50
COST_FOR_UNBAN = 100
COST_FOR_PHOTO = 50
MAX_WARNINGS = 3

# Этот сет будет хранить ID админов, которые вошли в систему
# Он будет сбрасываться при каждом перезапуске бота
ADMIN_IDS = set()

# Словарь с доступными интересами
AVAILABLE_INTERESTS = {
    "Музыка": "🎵", "Игры": "🎮", "Кино": "🎬",
    "Путешествия": "✈️", "Общение": "💬", "18+": "🔞"
}
