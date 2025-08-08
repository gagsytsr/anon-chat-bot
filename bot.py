import os
import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

TOKEN = os.getenv("TOKEN")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

if not TOKEN or not ADMIN_PASSWORD:
    raise ValueError("❌ Не задан TOKEN или ADMIN_PASSWORD в переменных окружения Railway!")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2))
dp = Dispatcher()

waiting_users = {}
active_chats = {}
user_data = {}
nick_consent = {}  # храним согласия на показ ника

SEARCH_TIMEOUT = 120  # 2 минуты
CHAT_DURATION = 600   # 10 минут

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
    active_chats[user1] = {'partner': user2, 'start_time': datetime.now()}
    active_chats[user2] = {'partner': user1, 'start_time': datetime.now()}
    waiting_users.pop(user1, None)
    waiting_users.pop(user2, None)
    nick_consent[user1] = False
    nick_consent[user2] = False

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙋‍♂️ Запросить ник собеседника", callback_data="request_nick")],
        [InlineKeyboardButton(text="❌ Завершить", callback_data="stop_chat")]
    ])

    await bot.send_message(user1, "✅ Собеседник найден! Можете начинать общение.", reply_markup=kb)
    await bot.send_message(user2, "✅ Собеседник найден! Можете начинать общение.", reply_markup=kb)

    await asyncio.sleep(CHAT_DURATION)
    if user1 in active_chats and user2 in active_chats:
        await stop_chat(user1)

async def stop_chat(user_id):
    partner_info = active_chats.get(user_id)
    if partner_info:
        partner_id = partner_info['partner']
        await bot.send_message(user_id, "⏹ Диалог завершён.")
        await bot.send_message(partner_id, "⏹ Диалог завершён.")
        active_chats.pop(user_id, None)
        active_chats.pop(partner_id, None)
        nick_consent.pop(user_id, None)
        nick_consent.pop(partner_id, None)

@dp.message(Command("start"))
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

@dp.callback_query(lambda c: c.data == "stop_chat")
async def callback_stop_chat(call: types.CallbackQuery):
    await stop_chat(call.from_user.id)

@dp.callback_query(lambda c: c.data == "request_nick")
async def callback_request_nick(call: types.CallbackQuery):
    user_id = call.from_user.id
    partner_info = active_chats.get(user_id)
    if not partner_info:
        return await call.answer("❌ Вы не в активном чате.", show_alert=True)

    partner_id = partner_info['partner']
    start_time = partner_info['start_time']
    now = datetime.now()

    # Проверяем, прошло ли 10 минут
    if now - start_time < timedelta(minutes=10):
        await call.answer("⏳ Можно запросить ник только после 10 минут общения.", show_alert=True)
        return

    # Отмечаем согласие пользователя на показать ник
    nick_consent[user_id] = True

    if nick_consent.get(partner_id):
        # Оба согласны — показываем ник
        partner_username = user_data.get(partner_id, {}).get("username", "—")
        partner_username_escaped = escape_md(partner_username)
        await bot.send_message(user_id, f"👤 Ник собеседника: @{partner_username_escaped}")
        # Сброс согласий, чтобы нельзя было запросить снова без повторного согласия
        nick_consent[user_id] = False
        nick_consent[partner_id] = False
    else:
        await call.answer("✅ Запрос отправлен. Ждём согласия собеседника.", show_alert=True)
        await bot.send_message(partner_id, "💬 Ваш собеседник запросил показать свой ник. Нажмите /agree, чтобы согласиться.")

@dp.message(Command("agree"))
async def cmd_agree(message: types.Message):
    user_id = message.from_user.id
    partner_info = active_chats.get(user_id)
    if not partner_info:
        return await message.answer("❌ Вы не в активном чате.")

    partner_id = partner_info['partner']
    if nick_consent.get(partner_id):
        # Оба согласны — показываем ник собеседнику
        partner_username = user_data.get(user_id, {}).get("username", "—")
        partner_username_escaped = escape_md(partner_username)
        await bot.send_message(partner_id, f"👤 Ник собеседника: @{partner_username_escaped}")
        # Сброс согласий
        nick_consent[user_id] = False
        nick_consent[partner_id] = False
        await message.answer("✅ Вы согласились показать свой ник.")
    else:
        # Отмечаем согласие этого пользователя, но собеседник пока не запросил ник
        nick_consent[user_id] = True
        await message.answer("✅ Вы согласились показать свой ник. Ждём запроса от собеседника.")

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    args = message.text.split()
    if len(args) != 2:
        return await message.answer("❌ Использование: /admin <пароль>")
    if args[1] != ADMIN_PASSWORD:
        return await message.answer("🚫 Неверный пароль.")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🚫 Завершить все чаты", callback_data="admin_stop_all")]
    ])
    await message.answer("🔐 Админ-панель", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats(call: types.CallbackQuery):
    total_users = len(user_data)
    active_pairs = len(active_chats) // 2
    await call.message.answer(f"📊 Пользователей всего: {total_users}\n💬 Активных чатов: {active_pairs}")

@dp.callback_query(lambda c: c.data == "admin_stop_all")
async def admin_stop_all(call: types.CallbackQuery):
    for uid in list(active_chats.keys()):
        await stop_chat(uid)
    await call.message.answer("🚫 Все чаты завершены.")

@dp.message()
async def relay_message(message: types.Message):
    if message.from_user.id in active_chats:
        partner_id = active_chats[message.from_user.id]['partner']
        await bot.send_message(partner_id, message.text)

async def main() -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
