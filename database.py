# database.py

import asyncpg
import os
import json # Добавляем для работы с JSON
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
        # Эта строка исправляет это автоматически
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
            # НОВАЯ ТАБЛИЦА: Очередь поиска
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS search_queue (
                    user_id BIGINT PRIMARY KEY,
                    interests TEXT, -- Будем хранить интересы как JSON-строку
                    added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
            """)
            # НОВАЯ ТАБЛИЦА: Активные чаты
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

# --- Функции управления поиском (вместо waiting_users) ---

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
        # Выбираем всех, кто в поиске, кроме самого себя
        potential_partners = await connection.fetch("SELECT user_id, interests FROM search_queue WHERE user_id != $1;", user_id)
        for partner in potential_partners:
            partner_interests_set = set(json.loads(partner['interests']))
            # Если есть хотя бы один общий интерес
            if user_interests_set & partner_interests_set:
                return partner['user_id'] # Возвращаем ID найденного партнера
    return None

# --- Функции управления чатами (вместо active_chats) ---

async def create_chat(user1_id: int, user2_id: int):
    """Создает запись об активном чате."""
    async with db_pool.acquire() as connection:
        await connection.execute("INSERT INTO active_chats (user1_id, user2_id) VALUES ($1, $2);", user1_id, user2_id)

async def get_partner_id(user_id: int) -> Optional[int]:
    """Находит ID партнера по чату."""
    async with db_pool.acquire() as connection:
        # Ищем в обоих столбцах
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

# --- Существующие функции (без серьезных изменений) ---
# ... (все твои функции, такие как ensure_user, is_user_banned и т.д., остаются здесь)
async def ensure_user(user_id: int, username: str = None):
    """
    Гарантирует, что пользователь существует в базе данных.
    Если нет - создаёт. Если есть - обновляет username, если он изменился.
    Улучшенная версия: обновляет только при необходимости.
    """
    async with db_pool.acquire() as connection:
        await connection.execute("""
            INSERT INTO users (user_id, username) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
            WHERE users.username IS DISTINCT FROM EXCLUDED.username;
        """, user_id, username)

# ... (остальные твои функции ban_user, get_balance и т.д. без изменений)
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
        # Используем транзакцию для гарантии целостности данных
        async with connection.transaction():
            # Проверяем, был ли этот юзер уже кем-то приглашен
            existing_referrer = await connection.fetchval("SELECT invited_by FROM users WHERE user_id = $1;", new_user_id)
            # Условие: пользователь пришел сам (invited_by IS NULL) и это не его первый старт
            user_record = await connection.fetchrow("SELECT created_at FROM users WHERE user_id = $1;", new_user_id)
            if existing_referrer is None and user_record:
                await connection.execute("UPDATE users SET invited_by = $1 WHERE user_id = $2;", referrer_id, new_user_id)
                await connection.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = $1;", referrer_id)
                return True # Успешно
    return False # Пользователь уже был приглашен или это его первый запуск
# database.py

# ... (весь существующий код до этого места) ...

# --- НОВЫЕ Функции для Админки ---

async def get_bot_statistics() -> dict:
    """Собирает основную статистику по боту."""
    async with db_pool.acquire() as connection:
        total_users = await connection.fetchval("SELECT COUNT(*) FROM users;")
        banned_users = await connection.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE;")
        # Считаем количество записей в чатах и умножаем на 2, т.к. в каждом чате 2 человека
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
        await connection.execute("DELETE FROM д файла без изменений)
