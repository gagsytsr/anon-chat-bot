import asyncpg
import os
import json
from typing import Optional, List, Tuple

# Пул соединений будет создан при запуске бота
db_pool: Optional[asyncpg.Pool] = None

async def init_db():
    """
    Инициализирует пул соединений с PostgreSQL и создаёт все необходимые таблицы.
    """
    global db_pool
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise Exception("Переменная окружения DATABASE_URL не найдена!")

    try:
        # Railway может подставлять postgres://, а asyncpg требует postgresql://
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        
        db_pool = await asyncpg.create_pool(database_url)
        async with db_pool.acquire() as connection:
            # Таблица пользователей
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
            # Таблица: Очередь поиска
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS search_queue (
                    user_id BIGINT PRIMARY KEY,
                    interests TEXT,
                    added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
            """)
            # Таблица: Активные чаты
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS active_chats (
                    id SERIAL PRIMARY KEY,
                    user1_id BIGINT NOT NULL UNIQUE,
                    user2_id BIGINT NOT NULL UNIQUE,
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
    """Собирает основную статистику по боту."""
    async with db_pool.acquire() as connection:
        total_users = await connection.fetchval("SELECT COUNT(*) FROM users;")
        banned_users = await connection.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE;")
        users_in_chats = await connection.fetchval("SELECT COUNT(*) * 2 FROM active_chats;")
        users_in_queue = await connection.fetchval("SELECT COUNT(*) FROM search_queue;")
        return {
            "total_users": total_users or 0,
            "banned_users": banned_users or 0,
            "users_in_chats": users_in_chats or 0,
            "users_in_queue": users_in_queue or 0,
        }

async def get_all_active_chat_users() -> list:
    """Возвращает список ID всех пользователей в активных чатах."""
    async with db_pool.acquire() as connection:
        records = await connection.fetch("SELECT user1_id, user2_id FROM active_chats;")
        user_ids = []
        for record in records:
            user_ids.append(record['user1_id'])
            user_ids.append(record['user2_id'])
        return user_ids

async def clear_all_active_chats():
    """Удаляет все записи об активных чатах."""
    async with db_pool.acquire() as connection:
        await connection.execute("DELETE FROM active_chats;")

# --- Функции управления поиском ---

async def add_to_search_queue(user_id: int, interests: List[str]):
    """Добавляет пользователя в очередь поиска."""
    async with db_pool.acquire() as connection:
        interests_json = json.dumps(interests)
        await connection.execute(
            "INSERT INTO search_queue (user_id, interests) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET interests = $2;",
            user_id, interests_json
        )

async def remove_from_search_queue(user_id: int):
    """Удаляет пользователя из очереди поиска."""
    async with db_pool.acquire() as connection:
        await connection.execute("DELETE FROM search_queue WHERE user_id = $1;", user_id)

async def find_partner_in_queue(user_id: int, interests: List[str]) -> Optional[int]:
    """Ищет подходящего партнера в очереди."""
    user_interests_set = set(interests)
    async with db_pool.acquire() as connection:
        potential_partners = await connection.fetch("SELECT user_id, interests FROM search_queue WHERE user_id != $1;", user_id)
        for partner in potential_partners:
            partner_interests_set = set(json.loads(partner['interests']))
            if user_interests_set & partner_interests_set:
                return partner['user_id']
    return None

# --- Функции управления чатами ---

async def create_chat(user1_id: int, user2_id: int):
    """Создает запись об активном чате."""
    async with db_pool.acquire() as connection:
        await connection.execute("INSERT INTO active_chats (user1_id, user2_id) VALUES ($1, $2);", user1_id, user2_id)

async def get_partner_id(user_id: int) -> Optional[int]:
    """Находит ID партнера по чату."""
    async with db_pool.acquire() as connection:
        partner_id = await connection.fetchval(
            "SELECT user2_id FROM active_chats WHERE user1_id = $1 UNION SELECT user1_id FROM active_chats WHERE user2_id = $1;",
            user_id
        )
        return partner_id

async def delete_chat(user_id: int) -> Optional[Tuple[int, int]]:
    """Удаляет чат, в котором участвует пользователь, и возвращает ID обоих участников."""
    async with db_pool.acquire() as connection:
        record = await connection.fetchrow(
            "DELETE FROM active_chats WHERE user1_id = $1 OR user2_id = $1 RETURNING user1_id, user2_id;",
            user_id
        )
        if record:
            return record['user1_id'], record['user2_id']
    return None

# --- Функции для пользователей ---

async def ensure_user(user_id: int, username: str = None):
    """Гарантирует, что пользователь существует в базе данных."""
    async with db_pool.acquire() as connection:
        await connection.execute("""
            INSERT INTO users (user_id, username) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
            WHERE users.username IS DISTINCT FROM EXCLUDED.username;
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
        async with connection.transaction():
            existing_referrer = await connection.fetchval("SELECT invited_by FROM users WHERE user_id = $1;", new_user_id)
            user_record = await connection.fetchrow("SELECT created_at FROM users WHERE user_id = $1;", new_user_id)
            if existing_referrer is None and user_record:
                await connection.execute("UPDATE users SET invited_by = $1 WHERE user_id = $2;", referrer_id, new_user_id)
                await connection.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = $1;", referrer_id)
                return True
    return False
