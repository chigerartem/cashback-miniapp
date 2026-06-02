"""Referral helpers — claim pending invite from Redis."""
from __future__ import annotations

import logging
import uuid

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User

log = logging.getLogger("referrals")


async def claim_pending_referral(
    session: AsyncSession,
    redis: Redis,
    tg_id: int,
) -> uuid.UUID | None:
    """If bot saved a pending_ref for this tg_id, look up referrer and return its UUID.

    Removes the Redis key on any outcome (claimed, invalid, self-ref).
    Returns None when there's nothing to claim or the code is bad.
    """
    key = f"pending_ref:{tg_id}"
    code = await redis.get(key)
    if not code:
        return None

    try:
        referrer = (
            await session.execute(select(User).where(User.ref_code == code))
        ).scalar_one_or_none()
    except Exception:
        log.exception("claim_pending_referral lookup failed tg_id=%s", tg_id)
        await redis.delete(key)
        return None

    await redis.delete(key)

    if referrer is None:
        log.info("pending_ref code=%s not found in users", code)
        return None
    if referrer.tg_id == tg_id:
        log.info("pending_ref self-referral ignored tg_id=%s", tg_id)
        return None
    if referrer.is_blocked:
        log.info("pending_ref referrer is blocked, ignored")
        return None

    log.info("referral claimed: tg_id=%s → referrer=%s", tg_id, referrer.id)
    return referrer.id
