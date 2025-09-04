import asyncpg
import os
import json
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
                    invited_by BIGINT, referral_count INTEGER DEFAULT 0 NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS search_queue (
                    user_id BIGINT PRIMARY KEY, interests TEXT, added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS active_chats (
                    id SERIAL PRIMARY KEY, user1_id BIGINT NOT NULL UNIQUE, user2_id BIGINT NOT NULL UNIQUE,
                    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user1_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    FOREIGN KEY (user2_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
            """)
        print("✅ База данных успешно инициализирована.")
    except Exception as e:
        print(f"❌ Ошибка инициализации базы данных: {e}")
        raise

# --- Функции для Админки ---
async def get_bot_statistics() -> dict:
    async with db_pool.acquire() as connection:
        return {
            "total_users": await connection.fetchval("SELECT COUNT(*) FROM users;") or 0,
            "banned_users": await connection.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE;") or 0,
            "users_in_chats": await connection.fetchval("SELECT COUNT(*) * 2 FROM active_chats;") or 0,
            "users_in_queue": await connection.fetchval("SELECT COUNT(*) FROM search_queue;") or 0,
        }

async def get_all_active_chat_users() -> list:
    async with db_pool.acquire() as conn:
        records = await conn.fetch("SELECT user1_id, user2_id FROM active_chats;")
        return [user_id for record in records for user_id in (record['user1_id'], record['user2_id'])]

async def clear_all_active_chats():
    async with db_pool.acquire() as conn: await conn.execute("DELETE FROM active_chats;")

# --- Функции управления поиском и чатами ---
async def add_to_search_queue(user_id: int, interests: List[str]):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO search_queue (user_id, interests) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET interests = $2;", user_id, json.dumps(interests))

async def find_partner_in_queue(user_id: int, interests: List[str]) -> Optional[int]:
    async with db_pool.acquire() as conn:
        partners = await conn.fetch("SELECT user_id, interests FROM search_queue WHERE user_id != $1;", user_id)
        for partner in partners:
            if set(interests) & set(json.loads(partner['interests'])):
                await conn.execute("DELETE FROM search_queue WHERE user_id = $1;", partner['user_id'])
                return partner['user_id']
    return None

async def create_chat(u1: int, u2: int):
    async with db_pool.acquire() as conn: await conn.execute("INSERT INTO active_chats (user1_id, user2_id) VALUES ($1, $2);", u1, u2)

async def get_partner_id(user_id: int) -> Optional[int]:
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT user2_id FROM active_chats WHERE user1_id = $1 UNION SELECT user1_id FROM active_chats WHERE user2_id = $1;", user_id)

async def delete_chat(user_id: int) -> Optional[Tuple[int, int]]:
    async with db_pool.acquire() as conn:
        rec = await conn.fetchrow("DELETE FROM active_chats WHERE user1_id = $1 OR user2_id = $1 RETURNING user1_id, user2_id;", user_id)
        return (rec['user1_id'], rec['user2_id']) if rec else None

# --- Функции для пользователей ---
async def ensure_user(user_id: int, username: str = None):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username WHERE users.username IS DISTINCT FROM EXCLUDED.username;", user_id, username)

async def is_user_banned(user_id: int) -> bool:
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT is_banned FROM users WHERE user_id = $1;", user_id) or False

async def ban_user(user_id: int):
    async with db_pool.acquire() as conn: await conn.execute("UPDATE users SET is_banned = TRUE WHERE user_id = $1;", user_id)

async def unban_user(user_id: int):
    async with db_pool.acquire() as conn: await conn.execute("UPDATE users SET is_banned = FALSE, warnings = 0 WHERE user_id = $1;", user_id)

async def get_balance(user_id: int) -> int:
    async with db_pool.acquire() as conn:
        return await conn.fetchval("SELECT balance FROM users WHERE user_id = $1;", user_id) or 0

async def update_balance(user_id: int, amount: int) -> Optional[int]:
    async with db_pool.acquire() as conn:
        return await conn.fetchval("UPDATE users SET balance = balance + $1 WHERE user_id = $2 RETURNING balance;", amount, user_id)

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
