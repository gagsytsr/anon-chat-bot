import asyncpg
import os
import logging

# ===== ПОДКЛЮЧЕНИЕ К БД =====
# Railway автоматически предоставит эту переменную
DATABASE_URL = os.environ.get("DATABASE_URL")

async def get_connection():
    """Устанавливает соединение с базой данных."""
    return await asyncpg.connect(DATABASE_URL)

# ===== ИНИЦИАЛИЗАЦИЯ ТАБЛИЦ =====
async def init_db():
    """
    Создает таблицы в базе данных, если они еще не существуют.
    Вызывается один раз при старте бота.
    """
    conn = await get_connection()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance INTEGER DEFAULT 0 NOT NULL,
                is_banned BOOLEAN DEFAULT FALSE NOT NULL,
                warnings INTEGER DEFAULT 0 NOT NULL,
                invited_by BIGINT,
                unlocked_18plus BOOLEAN DEFAULT FALSE NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        logging.info("Таблица 'users' успешно проверена/создана.")
    finally:
        await conn.close()

# ===== ФУНКЦИИ-ПОМОЩНИКИ =====
async def user_exists(user_id: int) -> bool:
    """Проверяет, существует ли пользователь в БД."""
    conn = await get_connection()
    try:
        return await conn.fetchval("SELECT 1 FROM users WHERE user_id = $1", user_id) is not None
    finally:
        await conn.close()

# ===== ОСНОВНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С ПОЛЬЗОВАТЕЛЯМИ =====
async def get_or_create_user(user_id: int, username: str = None, first_name: str = None):
    """
    Получает пользователя из БД. Если его нет, создает новую запись.
    Также обновляет username и first_name, если они изменились.
    """
    conn = await get_connection()
    try:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if user is None:
            await conn.execute(
                "INSERT INTO users (user_id, username, first_name) VALUES ($1, $2, $3)",
                user_id, username, first_name
            )
            user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        else:
            # Обновляем данные, если они изменились
            if user['username'] != username or user['first_name'] != first_name:
                await conn.execute(
                    "UPDATE users SET username = $1, first_name = $2 WHERE user_id = $3",
                    username, first_name, user_id
                )
        return dict(user)
    finally:
        await conn.close()

async def get_user_data(user_id: int):
    """Возвращает все данные о пользователе."""
    return await get_or_create_user(user_id)

async def update_balance(user_id: int, amount: int) -> int:
    """
    Изменяет баланс пользователя на указанную сумму (может быть отрицательной).
    Возвращает новый баланс.
    """
    conn = await get_connection()
    try:
        await get_or_create_user(user_id)
        new_balance = await conn.fetchval(
            "UPDATE users SET balance = balance + $1 WHERE user_id = $2 RETURNING balance",
            amount, user_id
        )
        # Баланс не может быть отрицательным
        if new_balance < 0:
            new_balance = await conn.fetchval(
                "UPDATE users SET balance = 0 WHERE user_id = $1 RETURNING balance",
                user_id
            )
        return new_balance
    finally:
        await conn.close()

async def set_invited_by(user_id: int, referrer_id: int) -> bool:
    """Устанавливает реферера для нового пользователя."""
    conn = await get_connection()
    try:
        # Убедимся, что оба пользователя существуют
        await get_or_create_user(user_id)
        await get_or_create_user(referrer_id)
        
        existing_referrer = await conn.fetchval("SELECT invited_by FROM users WHERE user_id = $1", user_id)
        if existing_referrer is None:
            await conn.execute("UPDATE users SET invited_by = $1 WHERE user_id = $2", referrer_id, user_id)
            return True
        return False
    finally:
        await conn.close()

async def ban_user(user_id: int):
    """Банит пользователя и сбрасывает его предупреждения."""
    conn = await get_connection()
    try:
        await get_or_create_user(user_id)
        await conn.execute("UPDATE users SET is_banned = TRUE, warnings = 0 WHERE user_id = $1", user_id)
    finally:
        await conn.close()

async def unban_user(user_id: int):
    """Разбанивает пользователя и сбрасывает предупреждения."""
    conn = await get_connection()
    try:
        await get_or_create_user(user_id)
        await conn.execute("UPDATE users SET is_banned = FALSE, warnings = 0 WHERE user_id = $1", user_id)
    finally:
        await conn.close()

async def add_warning(user_id: int) -> int:
    """Добавляет предупреждение пользователю и возвращает их новое количество."""
    conn = await get_connection()
    try:
        await get_or_create_user(user_id)
        return await conn.fetchval(
            "UPDATE users SET warnings = warnings + 1 WHERE user_id = $1 RETURNING warnings",
            user_id
        )
    finally:
        await conn.close()
        
async def unlock_18plus(user_id: int):
    """Открывает доступ к категории 18+."""
    conn = await get_connection()
    try:
        await get_or_create_user(user_id)
        await conn.execute("UPDATE users SET unlocked_18plus = TRUE WHERE user_id = $1", user_id)
    finally:
        await conn.close()

# ===== ФУНКЦИИ ДЛЯ СТАТИСТИКИ (АДМИНКА) =====
async def get_stats():
    """Собирает общую статистику для админ-панели."""
    conn = await get_connection()
    try:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        banned_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE")
        total_balance = await conn.fetchval("SELECT SUM(balance) FROM users")
        total_referrals = await conn.fetchval("SELECT COUNT(*) FROM users WHERE invited_by IS NOT NULL")
        return {
            "total_users": total_users or 0,
            "banned_users": banned_users or 0,
            "total_balance": total_balance or 0,
            "total_referrals": total_referrals or 0,
        }
    finally:
        await conn.close()

async def get_referral_count(user_id: int) -> int:
    """Считает, сколько пользователей пригласил данный юзер."""
    conn = await get_connection()
    try:
        return await conn.fetchval("SELECT COUNT(*) FROM users WHERE invited_by = $1", user_id) or 0
    finally:
        await conn.close()

