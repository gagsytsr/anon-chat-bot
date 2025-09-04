import asyncpg
import os
import logging

DATABASE_URL = os.environ.get("DATABASE_URL")

# ===== ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ =====
async def init_db():
    """
    Инициализирует базу данных: создает таблицы, если они не существуют.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                is_banned BOOLEAN DEFAULT FALSE,
                warnings INTEGER DEFAULT 0,
                invited_by BIGINT,
                unlocked_18plus BOOLEAN DEFAULT FALSE
            );
        """)
        logging.info("Таблица 'users' успешно проверена/создана.")
    finally:
        await conn.close()

# ===== ФУНКЦИИ ДЛЯ РАБОТЫ С ПОЛЬЗОВАТЕЛЯМИ =====
async def get_or_create_user(user_id: int):
    """
    Получает пользователя из БД или создает нового, если его нет.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if user is None:
            await conn.execute("INSERT INTO users (user_id) VALUES ($1)", user_id)
            user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        return user
    finally:
        await conn.close()

async def update_balance(user_id: int, amount: int):
    """
    Обновляет баланс пользователя. amount может быть положительным или отрицательным.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await get_or_create_user(user_id) # Убедимся, что пользователь существует
        new_balance = await conn.fetchval(
            "UPDATE users SET balance = balance + $1 WHERE user_id = $2 RETURNING balance",
            amount, user_id
        )
        return new_balance
    finally:
        await conn.close()

async def get_balance(user_id: int):
    """
    Получает текущий баланс пользователя.
    """
    user = await get_or_create_user(user_id)
    return user['balance']

async def set_invited_by(user_id: int, referrer_id: int):
    """
    Устанавливает, кем был приглашен пользователь.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Проверяем, что пользователь еще не был кем-то приглашен
        existing_referrer = await conn.fetchval("SELECT invited_by FROM users WHERE user_id = $1", user_id)
        if existing_referrer is None:
            await conn.execute("UPDATE users SET invited_by = $1 WHERE user_id = $2", referrer_id, user_id)
            return True # Успешно установили реферера
        return False # Реферер уже был
    finally:
        await conn.close()
        
async def get_referral_count(user_id: int):
    """
    Считает количество пользователей, приглашенных данным user_id.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE invited_by = $1", user_id)
        return count or 0
    finally:
        await conn.close()

async def ban_user(user_id: int):
    """
    Банит пользователя.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await get_or_create_user(user_id)
        await conn.execute("UPDATE users SET is_banned = TRUE, warnings = 0 WHERE user_id = $1", user_id)
    finally:
        await conn.close()

async def unban_user(user_id: int):
    """
    Разбанивает пользователя.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await get_or_create_user(user_id)
        await conn.execute("UPDATE users SET is_banned = FALSE, warnings = 0 WHERE user_id = $1", user_id)
    finally:
        await conn.close()

async def get_user_status(user_id: int):
    """
    Проверяет, забанен ли пользователь.
    """
    user = await get_or_create_user(user_id)
    return user['is_banned']

async def get_all_users_count():
    """
    Получает общее количество пользователей в базе.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetchval("SELECT COUNT(*) FROM users")
    finally:
        await conn.close()
        
async def get_banned_users_count():
    """
    Получает количество забаненных пользователей.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE")
    finally:
        await conn.close()

# Добавь другие функции по аналогии (например, для предупреждений, 18+ и т.д.)
