import os
import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Загружаем переменные окружения
TOKEN = os.getenv("TOKEN")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

if not TOKEN or not ADMIN_PASSWORD:
    raise ValueError("❌ Не задан TOKEN или ADMIN_PASSWORD в переменных окружения Railway!")

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализируем бота с parse_mode MarkdownV2 по умолчанию
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2))
dp = Dispatcher()

waiting_users = {}
active_chats = {}
user_data = {}

SEARCH_TIMEOUT = 120  # 2 минуты
CHAT_DURATION = 600   # 10 минут

def escape_md(text: str) -> str:
    """
    Экранирует спецсимволы для MarkdownV2.
    """
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return ''.join('\\' + c if c in escape_chars else c for c in text)

async def start_search(user_id):
    waiting_users[user_id] = datetime.now()
    await bot.send_message(user_id, escape_md("🔍 Ищу собеседника..."))
    await asyncio.sleep(SEARCH_TIMEOUT)

    if user_id in waiting_users:
        del waiting_users[user_id]
        await bot.send_message(user_id, escape_md("⏳ Поиск отменён — никого не нашлось."))

async def connect_users(user1, user2):
    active_chats[user1] = user2
    active_chats[user2] = user1
    waiting_users.pop(user1, None)
    waiting_users.pop(user2, None)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙋‍♂️ Показать ник", callback_data="show_nick")],
        [InlineKeyboardButton(text="❌ Завершить", callback_data="stop_chat")]
    ])

    await bot.send_message(user1, escape_md("✅ Собеседник найден! Можете начинать общение."), reply_markup=kb)
    await bot.send_message(user2, escape_md("✅ Собеседник найден! Можете начинать общение."), reply_markup=kb)

    await asyncio.sleep(CHAT_DURATION)
    if user1 in active_chats and user2 in active_chats:
        await stop_chat(user1)

async def stop_chat(user_id):
    partner_id = active_chats.get(user_id)
    if partner_id:
        await bot.send_message(user_id, escape_md("⏹ Диалог завершён."))
        await bot.send_message(partner_id, escape_md("⏹ Диалог завершён."))
        active_chats.pop(user_id, None)
        active_chats.pop(partner_id, None)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_data[message.from_user.id] = {"username": message.from_user.username}
    await message.answer(escape_md("👋 Привет! Нажми /search, чтобы найти собеседника\\."))

@dp.message(Command("search"))
async def cmd_search(message: types.Message):
    uid = message.from_user.id
    if uid in waiting_users or uid in active_chats:
        return await message.answer(escape_md("⏳ Вы уже ищете или общаетесь\\."))
    if waiting_users:
        partner_id = list(waiting_users.keys())[0]
        await connect_users(uid, partner_id)
    else:
        asyncio.create_task(start_search(uid))

@dp.callback_query(lambda c: c.data == "stop_chat")
async def callback_stop_chat(call: types.CallbackQuery):
    await stop_chat(call.from_user.id)

@dp.callback_query(lambda c: c.data == "show_nick")
async def callback_show_nick(call: types.CallbackQuery):
    partner_id = active_chats.get(call.from_user.id)
    if partner_id:
        partner_username = user_data.get(partner_id, {}).get("username", "—")
        partner_username_escaped = escape_md(partner_username)
        await bot.send_message(call.from_user.id, f"👤 Ник собеседника: @{partner_username_escaped}")

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    args = message.text.split()
    if len(args) != 2:
        return await message.answer(escape_md("❌ Использование: /admin <пароль>"))
    if args[1] != ADMIN_PASSWORD:
        return await message.answer(escape_md("🚫 Неверный пароль."))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🚫 Завершить все чаты", callback_data="admin_stop_all")]
    ])
    await message.answer(escape_md("🔐 Админ-панель"), reply_markup=kb)

@dp.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats(call: types.CallbackQuery):
    total_users = len(user_data)
    active_pairs = len(active_chats) // 2
    await call.message.answer(escape_md(f"📊 Пользователей всего: {total_users}\n💬 Активных чатов: {active_pairs}"))

@dp.callback_query(lambda c: c.data == "admin_stop_all")
async def admin_stop_all(call: types.CallbackQuery):
    for uid in list(active_chats.keys()):
        await stop_chat(uid)
    await call.message.answer(escape_md("🚫 Все чаты завершены."))

@dp.message()
async def relay_message(message: types.Message):
    if message.from_user.id in active_chats:
        await bot.send_message(active_chats[message.from_user.id], message.text)

async def main() -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
