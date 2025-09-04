# database.py
import asyncpg
import os
from typing import Optional

# Пул соединений будет создан при запуске бота
db_pool: Optional[asyncpg.Pool] = None

async def init_db():
    """
    Инициализирует пул соединений с базой данных PostgreSQL и создаёт
    таблицу 'users', если она ещё не существует.
    """
    global db_pool
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise Exception("Переменная окружения DATABASE_URL не найдена!")

    try:
        db_pool = await asyncpg.create_pool(database_url)
        async with db_pool.acquire() as connection:
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
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
        print("✅ База данных успешно инициализирована.")
    except Exception as e:
        print(f"❌ Ошибка инициализации базы данных: {e}")
        raise

async def ensure_user(user_id: int, username: str = None):
    """
    Гарантирует, что пользователь существует в базе данных.
    Если нет - создаёт. Если есть - может обновить его username.
    """
    async with db_pool.acquire() as connection:
        await connection.execute("""
            INSERT INTO users (user_id, username) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username;
        """, user_id, username)

async def is_user_banned(user_id: int) -> bool:
    """Проверяет, забанен ли пользователь."""
    async with db_pool.acquire() as connection:
        status = await connection.fetchval("SELECT is_banned FROM users WHERE user_id = $1;", user_id)
        return status or False

async def ban_user(user_id: int):
    """Банит пользователя."""
    async with db_pool.acquire() as connection:
        await connection.execute("UPDATE users SET is_banned = TRUE WHERE user_id = $1;", user_id)

async def unban_user(user_id: int):
    """Разбанивает пользователя и сбрасывает предупреждения."""
    async with db_pool.acquire() as connection:
        await connection.execute("UPDATE users SET is_banned = FALSE, warnings = 0 WHERE user_id = $1;", user_id)

async def get_balance(user_id: int) -> int:
    """Получает баланс пользователя."""
    async with db_pool.acquire() as connection:
        balance = await connection.fetchval("SELECT balance FROM users WHERE user_id = $1;", user_id)
        return balance or 0

async def update_balance(user_id: int, amount_change: int) -> int:
    """Изменяет баланс пользователя и возвращает новый баланс."""
    async with db_pool.acquire() as connection:
        new_balance = await connection.fetchval("""
            UPDATE users SET balance = balance + $1 WHERE user_id = $2 RETURNING balance;
        """, amount_change, user_id)
        return new_balance

async def get_warnings(user_id: int) -> int:
    """Получает количество предупреждений пользователя."""
    async with db_pool.acquire() as connection:
        warnings = await connection.fetchval("SELECT warnings FROM users WHERE user_id = $1;", user_id)
        return warnings or 0

async def increment_warnings(user_id: int) -> int:
    """Увеличивает счётчик предупреждений на 1 и возвращает новое значение."""
    async with db_pool.acquire() as connection:
        new_warnings = await connection.fetchval("""
            UPDATE users SET warnings = warnings + 1 WHERE user_id = $1 RETURNING warnings;
        """, user_id)
        return new_warnings

async def reset_warnings(user_id: int):
    """Сбрасывает счётчик предупреждений."""
    async with db_pool.acquire() as connection:
        await connection.execute("UPDATE users SET warnings = 0 WHERE user_id = $1;", user_id)

async def has_unlocked_18plus(user_id: int) -> bool:
    """Проверяет, разблокировал ли пользователь 18+ контент."""
    async with db_pool.acquire() as connection:
        status = await connection.fetchval("SELECT unlocked_18plus FROM users WHERE user_id = $1;", user_id)
        return status or False

async def unlock_18plus(user_id: int):
    """Устанавливает флаг разблокировки 18+ контента."""
    async with db_pool.acquire() as connection:
        await connection.execute("UPDATE users SET unlocked_18plus = TRUE WHERE user_id = $1;", user_id)

async def get_referral_count(user_id: int) -> int:
    """Получает количество приглашённых пользователей."""
    async with db_pool.acquire() as connection:
        count = await connection.fetchval("SELECT referral_count FROM users WHERE user_id = $1;", user_id)
        return count or 0

async def add_referral(referrer_id: int, new_user_id: int):
    """Добавляет реферала и обновляет счётчик пригласившего."""
    async with db_pool.acquire() as connection:
        # Проверяем, был ли этот юзер уже кем-то приглашен
        existing_referrer = await connection.fetchval("SELECT invited_by FROM users WHERE user_id = $1;", new_user_id)
        if existing_referrer is None:
            await connection.execute("UPDATE users SET invited_by = $1 WHERE user_id = $2;", referrer_id, new_user_id)
            await connection.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = $1;", referrer_id)
            return True # Успешно
    return False # Пользователь уже был приглашен

