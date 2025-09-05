# main.py
import asyncio
import logging

from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)

from config import BOT_TOKEN
import database as db
import handlers

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

async def main():
    """Основная функция для запуска бота."""
    # Инициализация соединения с базой данных
    await db.init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Регистрация обработчиков
    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("admin", handlers.admin_command))
    app.add_handler(CallbackQueryHandler(handlers.handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.message_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.VOICE, handlers.media_handler))
    
    # Добавляем задачу для graceful shutdown
    app.post_shutdown(db.close_db)

    # Запуск бота
    await app.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.critical(f"Критическая ошибка при запуске бота: {e}")

