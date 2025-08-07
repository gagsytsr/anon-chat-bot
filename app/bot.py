# bot.py — aiogram logic: matchmaking, sessions, inline buttons
import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta
from .storage import storage

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()

# Keys in storage:
# "queue": list of user_ids waiting
# "user:{user_id}": {state, partner, timer_ts, nickname, ...}
# "session:{session_id}": {user_a, user_b, started_at, expires_at, revealed: {a:False,b:False}}

QUEUE_KEY = "queue"

# Inline keyboards
def found_kb(cancel_label="Закончить"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("Открыть ник (по согласию)", callback_data="reveal_request")],
        [InlineKeyboardButton(cancel_label, callback_data="end_chat")]
    ])

def reveal_confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("Согласен раскрыть ник", callback_data="reveal_confirm")],
        [InlineKeyboardButton("Нет", callback_data="reveal_decline")]
    ])

# Helpers
async def push_to_queue(user_id):
    q = await storage.get(QUEUE_KEY) or []
    if user_id in q:
        return
    q.append(user_id)
    await storage.set(QUEUE_KEY, q)
    # store user state
    await storage.set(f"user:{user_id}", {"state":"searching", "queued_at": datetime.utcnow().isoformat()})

async def pop_from_queue(exclude=None):
    q = await storage.get(QUEUE_KEY) or []
    if not q:
        return None
    # find first not equal to exclude
    for uid in q:
        if uid != exclude:
            q.remove(uid)
            await storage.set(QUEUE_KEY, q)
            return uid
    return None

async def remove_from_queue(user_id):
    q = await storage.get(QUEUE_KEY) or []
    if user_id in q:
        q.remove(user_id)
        await storage.set(QUEUE_KEY, q)

# Matchmaking with 2-minute timeout
SEARCH_TIMEOUT = int(os.getenv("SEARCH_TIMEOUT_SEC", 120))
CHAT_DURATION = int(os.getenv("CHAT_DURATION_SEC", 600))  # 10 minutes

async def try_match(user_id):
    partner = await pop_from_queue(exclude=user_id)
    if partner:
        # create session id
        session_id = f"{min(user_id, partner)}:{max(user_id, partner)}:{int(datetime.utcnow().timestamp())}"
        now = datetime.utcnow()
        expires = now + timedelta(seconds=CHAT_DURATION)
        session = {"user_a": user_id, "user_b": partner, "started_at": now.isoformat(), "expires_at": expires.isoformat(), "revealed": {str(user_id): False, str(partner): False}}
        await storage.set(f"session:{session_id}", session)
        # set users' partner ref
        await storage.set(f"user:{user_id}", {"state":"in_chat","partner":partner,"session":session_id})
        await storage.set(f"user:{partner}", {"state":"in_chat","partner":user_id,"session":session_id})
        # Notify users
        await bot.send_message(user_id, "Собеседник найден! 10 минут на общение. По желанию — можно открыть никнеймы по обоюдному согласию.", reply_markup=found_kb())
        await bot.send_message(partner, "Собеседник найден! 10 минут на общение. По желанию — можно открыть никнеймы по обоюдному согласию.", reply_markup=found_kb())
        # start chat expiry watcher
        asyncio.create_task(chat_expiry_watcher(session_id))
        return True
    else:
        return False

async def chat_expiry_watcher(session_id):
    session = await storage.get(f"session:{session_id}")
    if not session:
        return
    expires = datetime.fromisoformat(session["expires_at"])
    now = datetime.utcnow()
    to_wait = (expires - now).total_seconds()
    if to_wait > 0:
        await asyncio.sleep(to_wait)
    # end session
    await end_session(session_id, reason="time_up")

async def end_session(session_id, reason="ended"):
    session = await storage.get(f"session:{session_id}")
    if not session:
        return
    a = session["user_a"]
    b = session["user_b"]
    # notify
    await bot.send_message(a, f"Чат завершён ({reason}).", reply_markup=None)
    await bot.send_message(b, f"Чат завершён ({reason}).", reply_markup=None)
    # cleanup
    await storage.delete(f"session:{session_id}")
    await storage.set(f"user:{a}", {"state":"idle"})
    await storage.set(f"user:{b}", {"state":"idle"})

# Message handler: forward messages between partners
@dp.message()
async def on_message(message: types.Message):
    user = message.from_user
    uid = user.id
    uinfo = await storage.get(f"user:{uid}") or {}
    if uinfo.get("state") != "in_chat":
        await message.answer("Сначала начни поиск собеседника — /find")
        return
    partner = uinfo.get("partner")
    if not partner:
        await message.answer("Ошибка: партнер не найден.")
        return
    # forward text/media
    try:
        await message.copy_to(partner)
    except Exception as e:
        await message.answer("Ошибка при пересылке сообщения.")

# Commands
@dp.message(commands=["start","help"])
async def cmd_start(message: types.Message):
    await message.answer("Я — анонимный бот для случайных бесед.\nКоманды:\n/find — найти собеседника\n/stop — остановить поиск или завершить чат\n/report — пожаловаться на собеседника")

@dp.message(commands=["find"])
async def cmd_find(message: types.Message):
    uid = message.from_user.id
    await push_to_queue(uid)
    await message.answer("Ищу собеседника (ожидание до 2 минут)...")
    # try match immediately
    matched = await try_match(uid)
    if matched:
        return
    # otherwise wait up to SEARCH_TIMEOUT
    await asyncio.sleep(SEARCH_TIMEOUT)
    # check if still searching
    uinfo = await storage.get(f"user:{uid}") or {}
    if uinfo.get("state") == "searching":
        # cancel
        await remove_from_queue(uid)
        await storage.set(f"user:{uid}", {"state":"idle"})
        await message.answer("К сожалению, собеседник не найден за 2 минуты. Попробуй позже.")

@dp.message(commands=["stop"])
async def cmd_stop(message: types.Message):
    uid = message.from_user.id
    uinfo = await storage.get(f"user:{uid}") or {}
    if uinfo.get("state") == "searching":
        await remove_from_queue(uid)
        await storage.set(f"user:{uid}", {"state":"idle"})
        await message.answer("Поиск отменён.")
    elif uinfo.get("state") == "in_chat":
        session_id = uinfo.get("session")
        await end_session(session_id, reason="пользователь завершил чат")
    else:
        await message.answer("Нет активного поиска или чата.")

# Callback handlers for reveal/end
@dp.callback_query()
async def cb_handler(query: types.CallbackQuery):
    data = query.data
    uid = query.from_user.id
    uinfo = await storage.get(f"user:{uid}") or {}
    if data == "end_chat":
        if uinfo.get("state") == "in_chat":
            await end_session(uinfo.get("session"), reason="пользователь завершил чат")
            await query.answer("Чат завершён.")
        else:
            await query.answer("Нет активного чата.")
    elif data == "reveal_request":
        # send reveal request to partner
        if uinfo.get("state") != "in_chat":
            await query.answer("Нет активного чата.")
            return
        partner = uinfo.get("partner")
        await bot.send_message(partner, "Собеседник хочет открыть никнеймы. Вы согласны?", reply_markup=reveal_confirm_kb())
        await query.answer("Запрос отправлен партнёру.")
    elif data == "reveal_confirm":
        # partner agreed — reveal both if other also agreed. For simplicity: when one agrees we reveal both nicknames to each other.
        # In real app — require both confirmations. Here we implement two-step: one requests, other confirms - then reveal.
        # Find session by scanning user's session
        if uinfo.get("state") != "in_chat":
            await query.answer("Нет активного чата.")
            return
        session_id = uinfo.get("session")
        session = await storage.get(f"session:{session_id}")
        if not session:
            await query.answer("Сессия не найдена.")
            return
        # mark revealed for this user
        session["revealed"][str(uid)] = True
        # if both agreed -> send nicknames
        if all(session["revealed"].values()):
            a = session["user_a"]; b = session["user_b"]
            # fetch nicknames if set (use Telegram username as fallback)
            ua = (await bot.get_chat(a)).username or (await bot.get_chat(a)).first_name
            ub = (await bot.get_chat(b)).username or (await bot.get_chat(b)).first_name
            await bot.send_message(a, f"Ник вашего собеседника: @{ub}")
            await bot.send_message(b, f"Ник вашего собеседника: @{ua}")
        else:
            await query.answer("Вы подтвердили. Ждём подтверждения от партнёра.")
    elif data == "reveal_decline":
        await query.answer("Отклонено.")
