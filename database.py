import asyncpg
import os
from typing import Optional, List, Tuple

db_pool: Optional[asyncpg.Pool] = None

async def init_db():
    global db_pool
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise Exception("Переменная окружения DATABASE_URL не найдена!")
    try:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        db_pool = await asyncpg.create_pool(database_url)
        async with db_pool.acquire() as connection:
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 0 NOT NULL,
                    is_banned BOOLEAN DEFAULT FALSE NOT NULL, warnings INTEGER DEFAULT 0 NOT NULL,
                    invited_by BIGINT, unlocked_18plus BOOLEAN DEFAULT FALSE NOT NULL,
                    referral_count INTEGER DEFAULT 0 NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS active_chats (
                    user1_id BIGINT PRIMARY KEY,
                    user2_id BIGINT NOT NULL UNIQUE,
                    FOREIGN KEY (user1_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (user2_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
            """)
        print("✅ База данных успешно инициализирована.")
    except Exception as e:
        print(f"❌ Ошибка инициализации базы данных: {e}")
        raise

async def create_chat(user1_id: int, user2_id: int):
    async with db_pool.acquire() as connection:
        await connection.execute("INSERT INTO active_chats (user1_id, user2_id) VALUES ($1, $2);", user1_id, user2_id)

async def get_partner(user_id: int) -> Optional[int]:
    async with db_pool.acquire() as conn:
        res = await conn.fetchval("SELECT user2_id FROM active_chats WHERE user1_id = $1 UNION SELECT user1_id FROM active_chats WHERE user2_id = $1;", user_id)
        return res

async def delete_chat(user_id: int) -> Optional[Tuple[int, int]]:
    async with db_pool.acquire() as conn:
        record = await conn.fetchrow("DELETE FROM active_chats WHERE user1_id = $1 OR user2_id = $1 RETURNING user1_id, user2_id;", user_id)
        return (record['user1_id'], record['user2_id']) if record else None

# --- Все твои оригинальные функции для работы с пользователями ---
async def ensure_user(user_id: int, username: str = None):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING;", user_id, username)

async def is_user_banned(user_id: int) -> bool:
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT is_banned FROM users WHERE user_id = $1;", user_id) or False

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

async def get_warnings(user_id: int) -> int:
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT warnings FROM users WHERE user_id = $1;", user_id) or 0

async def increment_warnings(user_id: int) -> int:
    async with db_pool.acquire() as conn:
        return await conn.fetchval("UPDATE users SET warnings = warnings + 1 WHERE user_id = $1 RETURNING warnings;", user_id)

async def get_referral_count(user_id: int) -> int:
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT referral_count FROM users WHERE user_id = $1;", user_id) or 0

async def add_referral(referrer_id: int, new_user_id: int):
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            if await conn.fetchval("SELECT invited_by FROM users WHERE user_id = $1;", new_user_id) is None:
                await conn.execute("UPDATE users SET invited_by = $1 WHERE user_id = $2;", referrer_id, new_user_id)
                await conn.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = $1;", referrer_id)
                return True
    return False
