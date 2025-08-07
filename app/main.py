# main.py — Flask + автоматическая установка webhook
import os
import logging
import asyncio
import requests
from flask import Flask, request, jsonify
from aiogram.types import Update
from bot import dp, bot

# Настройка логов
logging.basicConfig(level=logging.INFO)

# Токен бота из переменной окружения
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN")

# URL сервиса Render (твой фиксированный адрес)
RENDER_URL = "https://anon-chat-bot-n21b.onrender.com"

# Путь и полный URL webhook
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_FULL_URL = f"{RENDER_URL}{WEBHOOK_PATH}"

# Flask-приложение
app = Flask(__name__)

@app.before_first_request
def setup_webhook():
    """Автоматическая установка webhook при старте приложения"""
    logging.info(f"Устанавливаю webhook на {WEBHOOK_FULL_URL}...")
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/setWebhook",
            params={"url": WEBHOOK_FULL_URL}
        )
        logging.info(f"Результат установки webhook: {r.text}")
    except Exception as e:
        logging.error(f"Ошибка при установке webhook: {e}")

@app.route("/")
def index():
    return "Anon Chat Bot is running."

@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    """Приём обновлений от Telegram через webhook"""
    try:
        data = request.get_json(force=True)
        update = Update(**data)
        asyncio.create_task(dp.feed_update(update))
    except Exception as e:
        logging.error(f"Ошибка при обработке webhook: {e}")
    return jsonify({"ok": True})

if __name__ == "__main__":
    # Локальный запуск для отладки
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
