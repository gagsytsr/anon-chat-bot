# bot.py
import asyncio
import json
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode

from config import TOKEN, ADMIN_ID

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

waiting_users = {}
active_chats = {}
user_data = {}

SEARCH_TIMEOUT = 120  # 2 минуты
CHAT_DURATION = 600   # 10 минут

def save_data():
    with open("data/users.json", "w", encoding="utf-8") as f:
        json.dump(user_data, f, ensure_ascii=False, indent=2)

async def start_search(user_id):
    waiting_users[user_id] = datetime.now()
    await bot.send_message(user_id, "🔍 Ищу собеседника...")
    await asyncio.sleep(SEARCH_TIMEOUT)

    if user_id in waiting_users:
        del waiting_users[user_id]
        await bot.send_message(user_id, "⏳ Поиск отменён — никого не нашлось.")

async def connect_users(user1, user2):
    active_chats[user1] = user2
    active_chats[user2] = user1
    waiting_users.pop(user1, None)
    waiting_users.pop(user2, None)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙋‍♂️ Показать ник", callback_data="show_nick")],
        [InlineKeyboardButton(text="❌ Завершить", callback_data="stop_chat")]
    ])

    await bot.send_message(user1, "✅ Собеседник найден! Можете начинать общение.", reply_markup=kb)
    await bot.send_message(user2, "✅ Собеседник найден! Можете начинать общение.", reply_markup=kb)

    await asyncio.sleep(CHAT_DURATION)
    if user1 in active_chats and user2 in active_chats:
        await stop_chat(user1)

async def stop_chat(user_id):
    partner_id = active_chats.get(user_id)
    if partner_id:
        await bot.send_message(user_id, "⏹ Диалог завершён.")
        await bot.send_message(partner_id, "⏹ Диалог завершён.")
        active_chats.pop(user_id, None)
        active_chats.pop(partner_id, None)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_data[message.from_user.id] = {"username": message.from_user.username}
    save_data()
    await message.answer("👋 Привет! Нажми /search чтобы найти собеседника.")

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

@dp.callback_query(lambda c: c.data == "stop_chat")
async def callback_stop_chat(call: types.CallbackQuery):
    await stop_chat(call.from_user.id)

@dp.callback_query(lambda c: c.data == "show_nick")
async def callback_show_nick(call: types.CallbackQuery):
    partner_id = active_chats.get(call.from_user.id)
    if partner_id:
        partner_username = user_data.get(partner_id, {}).get("username", "—")
        await bot.send_message(call.from_user.id, f"👤 Ник собеседника: @{partner_username}")

@dp.message()
async def relay_message(message: types.Message):
    if message.from_user.id in active_chats:
        await bot.send_message(active_chats[message.from_user.id], message.text)

if __name__ == "__main__":
    import asyncio
    asyncio.run(dp.start_polling(bot))
