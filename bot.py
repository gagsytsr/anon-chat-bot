import os
import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, BotCommand
from aiogram.filters import Command, CommandStart
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

# ========== НАСТРОЙКИ СЕРВЕРА ==========
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = os.getenv("PORT", 8080)
WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = int(PORT)

# ========== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ==========
TOKEN = os.getenv("TOKEN")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

if not TOKEN or not ADMIN_PASSWORD:
    raise ValueError("❌ Не задан TOKEN или ADMIN_PASSWORD в переменных окружения!")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2))
dp = Dispatcher()

# Глобальные хранилища данных
waiting_users = {}
active_chats = {}
user_data = {}
nickname_requests = {}
SEARCH_TIMEOUT = 120  # 2 минуты
CHAT_DURATION = 600   # 10 минут
NICKNAME_WAIT = 600   # 10 минут

def escape_md(text: str) -> str:
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return ''.join('\\' + c if c in escape_chars else c for c in text)

async def start_search(user_id):
    waiting_users[user_id] = datetime.now()
    await bot.send_message(user_id, "🔍 Ищу собеседника...")
    await asyncio.sleep(SEARCH_TIMEOUT)
    if user_id in waiting_users:
        del waiting_users[user_id]
        await bot.send_message(user_id, "⏳ Поиск отменён — никого не нашлось.")

async def connect_users(user1, user2):
    active_chats[user1] = {"partner": user2, "start_time": datetime.now()}
    active_chats[user2] = {"partner": user1, "start_time": datetime.now()}
    waiting_users.pop(user1, None)
    waiting_users.pop(user2, None)
    nickname_requests[user1] = False
    nickname_requests[user2] = False

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙋‍♂️ Показать ник", callback_data="request_nick")],
        [InlineKeyboardButton(text="❌ Завершить", callback_data="stop_chat")]
    ])

    await bot.send_message(user1, "✅ Собеседник найден! Можете начинать общение.", reply_markup=kb)
    await bot.send_message(user2, "✅ Собеседник найден! Можете начинать общение.", reply_markup=kb)

    await asyncio.sleep(CHAT_DURATION)
    if user1 in active_chats and user2 in active_chats:
        await stop_chat(user1)

async def stop_chat(user_id):
    if user_id not in active_chats:
        return
    partner_id = active_chats[user_id]["partner"]
    await bot.send_message(user_id, "⏹ Диалог завершён.")
    await bot.send_message(partner_id, "⏹ Диалог завершён.")
    active_chats.pop(user_id, None)
    active_chats.pop(partner_id, None)
    nickname_requests.pop(user_id, None)
    nickname_requests.pop(partner_id, None)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_data[message.from_user.id] = {"username": message.from_user.username}
    await message.answer("👋 Привет! Нажми /search, чтобы найти собеседника.")

@dp.message(Command("search"))
async def cmd_search(message: types.Message):
    uid = message.from_user.id
    if uid in waiting_users or uid in active_chats:
        return await message.answer("⏳ Вы уже ищете или общаетесь.")
    if waiting_users:
        partner_id = list(waiting_users.keys())[0]
        await connect_users(uid, partner_id)
    else:
        asyncio.create_task(start_search(uid))

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message):
    uid = message.from_user.id
    if uid in waiting_users:
        waiting_users.pop(uid, None)
        await message.answer("❌ Поиск собеседника отменён.")
    else:
        await message.answer("ℹ️ Поиск не запущен или вы уже в чате.")

@dp.callback_query(F.data == "stop_chat")
async def callback_stop_chat(call: types.CallbackQuery):
    await call.answer()
    await stop_chat(call.from_user.id)

@dp.callback_query(F.data == "request_nick")
async def callback_request_nick(call: types.CallbackQuery):
    user_id = call.from_user.id
    await call.answer()
    if user_id not in active_chats:
        await call.answer("❌ Вы не в чате.", show_alert=True)
        return

    chat_info = active_chats[user_id]
    partner_id = chat_info["partner"]
    chat_start = chat_info["start_time"]

    if datetime.now() - chat_start < timedelta(seconds=NICKNAME_WAIT):
        await call.answer("⏳ Ники можно показать только спустя 10 минут общения.", show_alert=True)
        return

    nickname_requests[user_id] = True

    if nickname_requests.get(partner_id):
        partner_username = user_data.get(partner_id, {}).get("username", "—")
        partner_username_escaped = escape_md(partner_username)
        await bot.send_message(user_id, f"👤 Ник собеседника: @{partner_username_escaped}")
        await bot.send_message(partner_id, f"👤 Ник собеседника: @{escape_md(user_data.get(user_id, {}).get('username', '—'))}")
    else:
        await call.answer("✅ Запрос на показ ника отправлен партнёру. Ожидайте согласия.", show_alert=True)

@dp.message()
async def relay_message(message: types.Message):
    user_id = message.from_user.id
    if user_id in active_chats:
        partner_id = active_chats[user_id]["partner"]
        if message.text:
            await bot.send_message(partner_id, message.text)

async def on_startup(dispatcher, bot: Bot):
    await bot.set_webhook(url=WEBHOOK_URL)

async def main() -> None:
    dp.startup.register(on_startup)
    app = web.Application()
    app["bot"] = bot
    app.router.add_post(f"/{TOKEN}", dp.get_web_app())
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)
    await site.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
