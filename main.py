# main.py

import asyncio
import logging
import os
import re
import sys  # Добавляем sys для flush
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
import database
import keyboards

# ===== НАСТРОЙКИ ЛОГИРОВАНИЯ =====
# Мы будем использовать print для самого раннего логирования, до настройки основной системы
print("--- CHECKPOINT 0: Скрипт запущен, базовые импорты выполнены. ---")
sys.stdout.flush()

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# ... (весь остальной код до функции main() остается без изменений) ...
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = {int(admin_id.strip()) for admin_id in ADMIN_IDS_STR.split(',') if admin_id.strip()}
if not BOT_TOKEN:
    # logging.error еще может не работать, поэтому дублируем в print
    print("!!! ОШИБКА: BOT_TOKEN не установлен!")
    exit(1)
REWARD_FOR_REFERRAL = 10
COST_FOR_18PLUS = 50
COST_FOR_UNBAN = 100
MAX_WARNINGS = 3
available_interests = {
    "Музыка": "🎵", "Игры": "🎮", "Кино": "🎬",
    "Путешествия": "✈️", "Общение": "💬", "18+": "🔞"
}
# --- Тут идут все твои функции-обработчики (start, admin_command, message_handler, etc.) ---
# Мы их не меняем, поэтому я их скрою для краткости
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await database.ensure_user(user.id, user.username)
    if context.args and context.args[0].isdigit():
        referrer_id = int(context.args[0])
        if referrer_id != user.id:
            await database.ensure_user(referrer_id)
            if await database.add_referral(referrer_id, user.id):
                await database.update_balance(referrer_id, REWARD_FOR_REFERRAL)
                try:
                    await context.bot.send_message(
                        referrer_id,
                        f"🎉 Новый пользователь @{user.username} присоединился по вашей ссылке! Вам начислено {REWARD_FOR_REFERRAL} валюты."
                    )
                except Exception as e:
                    logging.warning(f"Не удалось отправить уведомление рефереру {referrer_id}: {e}")
    await update.message.reply_text(
        "👋 Добро пожаловать в анонимный чат!\n\n"
        "⚠️ Перед началом подтвердите согласие с правилами:\n"
        "• Запрещено нарушать законы.\n"
        "• Соблюдайте уважение.\n\n"
        "Нажмите 'Согласен' чтобы начать.",
        reply_markup=keyboards.get_agreement_keyboard()
    )
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id in ADMIN_IDS:
        context.user_data['is_admin_mode'] = True
        await update.message.reply_text(
            "🔐 Вы вошли в режим администратора.",
            reply_markup=keyboards.get_admin_reply_keyboard()
        )
    elif ADMIN_PASSWORD:
        await update.message.reply_text("🔐 Введите пароль администратора:")
        context.user_data["awaiting_admin_password"] = True
    else:
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Полный код handle_callback...
    pass
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Полный код message_handler...
    pass


# ====== ЗАПУСК БОТА С КОНТРОЛЬНЫМИ ТОЧКАМИ ======
async def main() -> None:
    """Запускает бота."""
    print("--- CHECKPOINT 1: Вход в функцию main(). Начинаем инициализацию. ---")
    sys.stdout.flush()
    try:
        print("--- CHECKPOINT 2: Инициализация базы данных... ---")
        sys.stdout.flush()
        await database.init_db()
        print("--- CHECKPOINT 3: База данных успешно инициализирована. ---")
        sys.stdout.flush()
    except Exception as e:
        print(f"!!! ОШИБКА НА ЭТАПЕ ИНИЦИАЛИЗАЦИИ БД: {e}")
        sys.stdout.flush()
        return

    print("--- CHECKPOINT 4: Очистка старых сессий... ---")
    sys.stdout.flush()
    async with database.db_pool.acquire() as conn:
        await conn.execute("DELETE FROM search_queue;")
        await conn.execute("DELETE FROM active_chats;")
    print("--- CHECKPOINT 5: Старые сессии очищены. ---")
    sys.stdout.flush()

    print("--- CHECKPOINT 6: Создание объекта Application... ---")
    sys.stdout.flush()
    app = Application.builder().token(BOT_TOKEN).build()
    print("--- CHECKPOINT 7: Объект Application создан. ---")
    sys.stdout.flush()

    print("--- CHECKPOINT 8: Добавление обработчиков... ---")
    sys.stdout.flush()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    print("--- CHECKPOINT 9: Обработчики добавлены. ---")
    sys.stdout.flush()
    
    async with app:
        print("--- CHECKPOINT 10: Вход в асинхронный контекст 'async with app'. ---")
        sys.stdout.flush()
        
        print("--- CHECKPOINT 11: Запуск app.start()... ---")
        sys.stdout.flush()
        await app.start()
        
        print("--- CHECKPOINT 12: Запуск app.updater.start_polling()... ---")
        sys.stdout.flush()
        await app.updater.start_polling()
        
        print("\n--- CHECKPOINT 13: БОТ УСПЕШНО ЗАПУЩЕН И РАБОТАЕТ. ---")
        sys.stdout.flush()
        
        # Бесконечный цикл, чтобы скрипт не завершался
        await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"!!! КРИТИЧЕСКАЯ ОШИБКА В __main__: {e}")
        sys.stdout.flush()

