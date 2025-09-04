import asyncio
import logging
import os
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from dotenv import load_dotenv

# Импортируем наши модули
import database as db
import handlers

# Загружаем переменные окружения из файла .env (для локального теста)
load_dotenv()

# ===== НАСТРОЙКИ ЛОГИРОВАНИЯ =====
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ===== ПЕРЕМЕННЫЕ =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Необходимо установить переменную окружения BOT_TOKEN!")

async def main():
    """Основная функция для запуска бота."""
    # 1. Инициализация базы данных при старте
    await db.init_db()
    
    # 2. Сборка приложения
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # 3. Регистрация обработчиков
    # Сначала команды
    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("admin", handlers.admin_command))
    
    # Затем обработчик нажатий на inline-кнопки
    app.add_handler(CallbackQueryHandler(handlers.callback_query_handler))
    
    # Обработчик медиа-файлов
    media_filters = filters.PHOTO | filters.VIDEO | filters.VOICE | filters.sticker
    app.add_handler(MessageHandler(media_filters & ~filters.COMMAND, handlers.media_handler))
    
    # Обработчик текста должен идти последним, чтобы не перехватывать команды
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.message_handler))

    # 4. Запуск бота
    logging.info("Бот запускается...")
    await app.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.critical(f"Критическая ошибка при запуске бота: {e}")

