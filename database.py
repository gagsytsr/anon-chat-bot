import asyncio
import asyncpg
from config import DATABASE_URL

pool = None

async def init_db():
    global pool
    if pool:
        return
    pool = await asyncpg.create_pool(DATABASE_URL)
    async with pool.acquire() as connection:
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance INTEGER DEFAULT 0 NOT NULL,
                is_banned BOOLEAN DEFAULT FALSE NOT NULL,
                warnings INTEGER DEFAULT 0 NOT NULL,
                agreed_to_rules BOOLEAN DEFAULT FALSE NOT NULL,
                unlocked_18plus BOOLEAN DEFAULT FALSE NOT NULL,
                invited_by BIGINT,
                referrals_count INTEGER DEFAULT 0 NOT NULL,
                interests TEXT[],
                status TEXT DEFAULT 'idle' NOT NULL,
                partner_id BIGINT
            );
        """)

async def close_db():
    if pool:
        await pool.close()

async def get_or_create_user(user_id: int):
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        if not user:
            await conn.execute("INSERT INTO users (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING", user_id)
            user = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        return user

# --- Функции управления пользователями ---
async def set_agreement(user_id: int, status: bool):
    await pool.execute("UPDATE users SET agreed_to_rules = $1 WHERE user_id = $2", status, user_id)

async def update_user_interests(user_id: int, interests: list):
    await pool.execute("UPDATE users SET interests = $1 WHERE user_id = $2", interests, user_id)

async def update_user_status(user_id: int, status: str):
    await pool.execute("UPDATE users SET status = $1, partner_id = NULL WHERE user_id = $2", status, user_id)

# --- Функции для чатов ---
async def find_partner(user_id: int, interests: list):
    query = "SELECT user_id FROM users WHERE status = 'waiting' AND user_id != $1 AND interests && $2::text[] LIMIT 1;"
    return await pool.fetchval(query, user_id, interests)

async def create_chat(user1_id: int, user2_id: int):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE users SET status = 'in_chat', partner_id = $1 WHERE user_id = $2", user2_id, user1_id)
        await conn.execute("UPDATE users SET status = 'in_chat', partner_id = $1 WHERE user_id = $2", user1_id, user2_id)

async def end_chat(user_id: int):
    partner_id = await pool.fetchval("SELECT partner_id FROM users WHERE user_id = $1", user_id)
    if partner_id:
        await pool.execute("UPDATE users SET status = 'idle', partner_id = NULL WHERE user_id = ANY($1::bigint[])", [user_id, partner_id])
    return partner_id

# --- Функции баланса и рефералов ---
async def update_balance(user_id: int, amount_change: int):
    return await pool.fetchval("UPDATE users SET balance = balance + $1 WHERE user_id = $2 RETURNING balance", amount_change, user_id)

async def add_referral(user_id: int, referrer_id: int, reward: int):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE users SET invited_by = $1 WHERE user_id = $2", referrer_id, user_id)
        await conn.execute("UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = $1", referrer_id)
        await update_balance(referrer_id, reward)

# --- Функции банов и предупреждений ---
async def set_ban_status(user_id: int, is_banned: bool):
    await pool.execute("UPDATE users SET is_banned = $1, warnings = 0 WHERE user_id = $2", is_banned, user_id)

async def add_warning(user_id: int):
    return await pool.fetchval("UPDATE users SET warnings = warnings + 1 WHERE user_id = $1 RETURNING warnings", user_id)

async def unlock_18plus(user_id: int):
    await pool.execute("UPDATE users SET unlocked_18plus = TRUE WHERE user_id = $1", user_id)

# --- Админ-функции ---
async def get_all_active_users():
    """Возвращает список ID всех пользователей в активных чатах."""
    return await pool.fetch("SELECT user_id FROM users WHERE status = 'in_chat'")

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
