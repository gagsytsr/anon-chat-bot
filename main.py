import asyncio
import logging
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)

import database as db
import handlers
from config import BOT_TOKEN

# Настраиваем логирование, чтобы видеть все сообщения в консоли Railway
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
# Устанавливаем более высокий уровень логирования для библиотеки, чтобы избежать спама
logging.getLogger("httpx").setLevel(logging.WARNING)

async def main():
    """Основная функция для настройки и запуска бота."""

    # Инициализация базы данных при старте
    await db.init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Регистрация всех обработчиков из файла handlers.py
    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("admin", handlers.admin_command))
    app.add_handler(CallbackQueryHandler(handlers.handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.message_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handlers.media_handler))

    # Отключаем эту строку, так как будем управлять остановкой по-другому
    # app.post_shutdown(db.close_db)

    # --- НОВЫЙ, БОЛЕЕ НАДЕЖНЫЙ СПОСОБ ЗАПУСКА ---
    # 1. Готовим приложение к работе
    await app.initialize()
    # 2. Запускаем фоновые задачи приложения
    await app.start()
    # 3. Запускаем получение обновлений от Telegram
    await app.updater.start_polling()

    # 4. Бот будет работать до тех пор, пока процесс не будет остановлен
    # (например, командой на Railway или Ctrl+C в консоли)
    await asyncio.Event().wait()

    # При остановке процесса (например, при перезапуске на Railway)
    # выполняем корректное завершение работы.
    await app.updater.stop()
    await app.stop()
    await db.close_db()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.critical("КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ БОТА:", exc_info=True)
