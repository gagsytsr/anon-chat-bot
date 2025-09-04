import asyncpg
import os
from typing import Optional, Tuple

db_pool: Optional[asyncpg.Pool] = None

async def init_db():
    """Инициализирует пул соединений и создаёт таблицы, если их нет."""
    global db_pool
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise Exception("Переменная окружения DATABASE_URL не найдена!")

    try:
        db_pool = await asyncpg.create_pool(database_url)
        async with db_pool.acquire() as connection:
            # Таблица пользователей с новыми полями status и is_admin
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    balance INTEGER DEFAULT 0 NOT NULL,
                    is_banned BOOLEAN DEFAULT FALSE NOT NULL,
                    warnings INTEGER DEFAULT 0 NOT NULL,
                    invited_by BIGINT,
                    unlocked_18plus BOOLEAN DEFAULT FALSE NOT NULL,
                    referral_count INTEGER DEFAULT 0 NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'idle' NOT NULL, -- 'idle', 'waiting', 'in_chat'
                    is_admin BOOLEAN DEFAULT FALSE NOT NULL
                );
            """)
            # Новая таблица для активных чатов
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS active_chats (
                    user1_id BIGINT PRIMARY KEY,
                    user2_id BIGINT UNIQUE NOT NULL
                );
            """)
        print("✅ База данных успешно инициализирована.")
    except Exception as e:
        print(f"❌ Ошибка инициализации базы данных: {e}")
        raise

# --- Функции для управления пользователями ---

async def ensure_user(user_id: int, username: str = None):
    """Гарантирует существование пользователя в БД."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username;",
            user_id, username
        )

async def is_user_banned(user_id: int) -> bool:
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT is_banned FROM users WHERE user_id = $1;", user_id)

async def ban_user(user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_banned = TRUE WHERE user_id = $1;", user_id)

async def unban_user(user_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_banned = FALSE, warnings = 0 WHERE user_id = $1;", user_id)

async def get_balance(user_id: int) -> int:
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT balance FROM users WHERE user_id = $1;", user_id) or 0

async def update_balance(user_id: int, amount_change: int):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET balance = balance + $1 WHERE user_id = $2;", amount_change, user_id)

async def increment_warnings(user_id: int) -> int:
    async with db_pool.acquire() as conn:
        return await conn.fetchval("UPDATE users SET warnings = warnings + 1 WHERE user_id = $1 RETURNING warnings;", user_id)

async def add_referral(referrer_id: int, new_user_id: int):
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            existing_referrer = await conn.fetchval("SELECT invited_by FROM users WHERE user_id = $1;", new_user_id)
            if existing_referrer is None:
                await conn.execute("UPDATE users SET invited_by = $1 WHERE user_id = $2;", referrer_id, new_user_id)
                await conn.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = $1;", referrer_id)
                return True
    return False

# --- Функции для управления админами ---

async def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь админом."""
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT is_admin FROM users WHERE user_id = $1;", user_id)

async def set_admin(user_id: int):
    """Назначает пользователя админом."""
    await ensure_user(user_id)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_admin = TRUE WHERE user_id = $1;", user_id)

# --- Функции для управления чатами и статусами (НОВОЕ) ---

async def get_user_status(user_id: int) -> str:
    """Получает статус пользователя."""
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT status FROM users WHERE user_id = $1;", user_id)

async def set_user_status(user_id: int, status: str):
    """Устанавливает статус пользователя."""
    await ensure_user(user_id)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET status = $1 WHERE user_id = $2;", status, user_id)

async def find_waiting_partner(user_id: int) -> Optional[int]:
    """Ищет партнера в статусе 'waiting'."""
    async with db_pool.acquire() as conn:
        # Простой поиск любого ожидающего, кроме себя. В будущем можно добавить логику интересов.
        partner_id = await conn.fetchval(
            "SELECT user_id FROM users WHERE status = 'waiting' AND user_id != $1 LIMIT 1;",
            user_id
        )
        return partner_id

async def create_chat(user1_id: int, user2_id: int):
    """Создает запись о чате в БД."""
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("INSERT INTO active_chats (user1_id, user2_id) VALUES ($1, $2);", user1_id, user2_id)
            await conn.execute("INSERT INTO active_chats (user1_id, user2_id) VALUES ($1, $2);", user2_id, user1_id)
            await set_user_status(user1_id, 'in_chat')
            await set_user_status(user2_id, 'in_chat')

async def get_partner_id(user_id: int) -> Optional[int]:
    """Получает ID партнера по чату."""
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT user2_id FROM active_chats WHERE user1_id = $1;", user_id)

async def delete_chat(user_id: int) -> Optional[int]:
    """Удаляет чат и возвращает ID бывшего партнера."""
    partner_id = await get_partner_id(user_id)
    if not partner_id:
        return None
        
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM active_chats WHERE user1_id = $1 OR user1_id = $2;", user_id, partner_id)
            await set_user_status(user_id, 'idle')
            await set_user_status(partner_id, 'idle')
    return partner_id

