# database.py
import asyncpg
from config import DATABASE_URL

# Пул соединений для повышения производительности
pool = None

async def init_db():
    """Инициализирует пул соединений и создает таблицу, если она не существует."""
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as connection:
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                is_banned BOOLEAN DEFAULT FALSE,
                warnings INTEGER DEFAULT 0,
                agreed_to_rules BOOLEAN DEFAULT FALSE,
                unlocked_18plus BOOLEAN DEFAULT FALSE,
                invited_by BIGINT,
                referrals_count INTEGER DEFAULT 0,
                interests TEXT[],
                status TEXT DEFAULT 'idle', -- 'idle', 'waiting', 'in_chat'
                partner_id BIGINT
            );
        """)

async def close_db():
    """Закрывает пул соединений."""
    await pool.close()

# --- Функции для управления пользователями ---

async def get_or_create_user(user_id: int):
    """Получает пользователя из БД или создает нового, если его нет."""
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not user:
            await conn.execute("INSERT INTO users (user_id) VALUES ($1)", user_id)
            user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        return user

async def set_agreement(user_id: int, status: bool):
    """Обновляет статус согласия с правилами."""
    await pool.execute("UPDATE users SET agreed_to_rules = $1 WHERE user_id = $2", status, user_id)

# --- Функции для чатов ---

async def find_partner(user_id: int, interests: list):
    """Ищет партнера с пересекающимися интересами."""
    # `&&` - это оператор пересечения массивов в PostgreSQL
    query = """
        SELECT user_id FROM users
        WHERE status = 'waiting' AND user_id != $1 AND interests && $2
        LIMIT 1;
    """
    partner = await pool.fetchval(query, user_id, interests)
    return partner

async def create_chat(user1_id: int, user2_id: int):
    """Создает чат между двумя пользователями."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("UPDATE users SET status = 'in_chat', partner_id = $1 WHERE user_id = $2", user2_id, user1_id)
            await conn.execute("UPDATE users SET status = 'in_chat', partner_id = $1 WHERE user_id = $2", user1_id, user2_id)

async def end_chat(user_id: int):
    """Завершает чат для пользователя и его партнера."""
    partner_id = await pool.fetchval("SELECT partner_id FROM users WHERE user_id = $1", user_id)
    if partner_id:
        await pool.execute("UPDATE users SET status = 'idle', partner_id = NULL WHERE user_id = ANY($1::bigint[])", [user_id, partner_id])
    return partner_id

async def update_user_status(user_id: int, status: str):
    """Обновляет статус пользователя (idle, waiting)."""
    await pool.execute("UPDATE users SET status = $1 WHERE user_id = $2", status, user_id)

async def update_user_interests(user_id: int, interests: list):
    """Обновляет интересы пользователя."""
    await pool.execute("UPDATE users SET interests = $1 WHERE user_id = $2", interests, user_id)


# --- Функции для баланса и рефералов ---

async def update_balance(user_id: int, amount: int, relative=True):
    """Обновляет баланс пользователя. relative=True для добавления/вычитания."""
    if relative:
        query = "UPDATE users SET balance = balance + $1 WHERE user_id = $2 RETURNING balance;"
    else:
        query = "UPDATE users SET balance = $1 WHERE user_id = $2 RETURNING balance;"
    return await pool.fetchval(query, amount, user_id)

async def add_referral(user_id: int, referrer_id: int, reward: int):
    """Добавляет реферала и начисляет награду."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("UPDATE users SET invited_by = $1 WHERE user_id = $2", referrer_id, user_id)
            await conn.execute("UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = $1", referrer_id)
            await update_balance(referrer_id, reward)

# --- Функции для банов и предупреждений ---

async def set_ban_status(user_id: int, is_banned: bool):
    """Устанавливает или снимает бан."""
    query = "UPDATE users SET is_banned = $1, warnings = 0 WHERE user_id = $2;"
    await pool.execute(query, is_banned, user_id)
    
async def add_warning(user_id: int):
    """Добавляет предупреждение и возвращает новое количество."""
    return await pool.fetchval("UPDATE users SET warnings = warnings + 1 WHERE user_id = $1 RETURNING warnings;", user_id)

async def unlock_18plus(user_id: int):
    """Отмечает, что пользователь разблокировал 18+ контент."""
    await pool.execute("UPDATE users SET unlocked_18plus = TRUE WHERE user_id = $1", user_id)


# --- Админ-функции ---

async def get_admin_stats():
    """Собирает статистику для админ-панели."""
    queries = [
        pool.fetchval("SELECT COUNT(*) FROM users WHERE agreed_to_rules = TRUE;"),
        pool.fetchval("SELECT COUNT(*) FROM users WHERE status = 'in_chat';"),
        pool.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE;"),
        pool.fetchval("SELECT SUM(referrals_count) FROM users;"),
        pool.fetchval("SELECT SUM(balance) FROM users;")
    ]
    results = await asyncio.gather(*queries)
    return {
        "total_users": results[0] or 0,
        "active_chats": (results[1] or 0) // 2,
        "banned_users": results[2] or 0,
        "total_referrals": results[3] or 0,
        "total_balance": results[4] or 0,
    }

