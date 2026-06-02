"""Shared async Redis client."""
from __future__ import annotations

from redis.asyncio import Redis

from app.config import settings

redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
