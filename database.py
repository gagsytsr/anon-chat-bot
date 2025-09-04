import os
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Boolean, BigInteger

DATABASE_URL = os.environ.get("DATABASE_URL")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
Base = declarative_base()

# Таблица пользователей
class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True, index=True)
    balance = Column(Integer, default=0)
    banned = Column(Boolean, default=False)
    warnings = Column(Integer, default=0)
    invited_by = Column(BigInteger, nullable=True)

# Таблица рефералов
class Referral(Base):
    __tablename__ = "referrals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, index=True)
    referrer_id = Column(BigInteger, index=True)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_user(user_id: int):
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            user = User(id=user_id, balance=0, banned=False, warnings=0)
            session.add(user)
            await session.commit()
        return user

async def update_balance(user_id: int, amount: int):
    async with async_session() as session:
        user = await get_user(user_id)
        user.balance += amount
        await session.merge(user)
        await session.commit()
        return user.balance
