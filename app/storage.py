# storage.py — поддерживает Redis (если задан REDIS_URL) или fallback на memory
import os
import json
import asyncio

REDIS_URL = os.getenv("REDIS_URL")

class InMemoryStorage:
    def __init__(self):
        self._data = {}
        self._lock = asyncio.Lock()

    async def set(self, key, value, ex=None):
        async with self._lock:
            self._data[key] = value

    async def get(self, key):
        async with self._lock:
            return self._data.get(key)

    async def delete(self, key):
        async with self._lock:
            if key in self._data:
                del self._data[key]

    async def keys(self, prefix=""):
        async with self._lock:
            return [k for k in self._data.keys() if k.startswith(prefix)]

try:
    import redis.asyncio as aioredis
    if REDIS_URL:
        _redis = aioredis.from_url(REDIS_URL)
    else:
        _redis = None
except Exception:
    _redis = None

class Storage:
    def __init__(self):
        self.memory = InMemoryStorage()
        self.redis = _redis

    async def set(self, key, value, ex=None):
        if self.redis:
            await self.redis.set(key, json.dumps(value), ex=ex)
        else:
            await self.memory.set(key, value)

    async def get(self, key):
        if self.redis:
            v = await self.redis.get(key)
            return json.loads(v) if v else None
        else:
            return await self.memory.get(key)

    async def delete(self, key):
        if self.redis:
            await self.redis.delete(key)
        else:
            await self.memory.delete(key)

    async def keys(self, prefix=""):
        if self.redis:
            ks = await self.redis.keys(f"{prefix}*")
            return [k.decode() if isinstance(k, bytes) else k for k in ks]
        else:
            return await self.memory.keys(prefix=prefix)

storage = Storage()
