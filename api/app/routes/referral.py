"""Referral statistics & link."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import telegram_user
from app.config import settings
from app.db import get_session
from app.models import CashbackEntry, User

router = APIRouter(prefix="/api/referral", tags=["referral"])


@router.get("")
async def get_referral(
    tg_user: dict = Depends(telegram_user),
    session: AsyncSession = Depends(get_session),
):
    tg_id = int(tg_user["id"])
    user = (
        await session.execute(select(User).where(User.tg_id == tg_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")

    invited_count = (
        await session.execute(
            select(func.count(User.id)).where(User.referrer_id == user.id)
        )
    ).scalar_one()

    earned_total: Decimal = (
        await session.execute(
            select(func.coalesce(func.sum(CashbackEntry.amount_usd), 0)).where(
                CashbackEntry.user_id == user.id,
                CashbackEntry.kind == "referral",
            )
        )
    ).scalar_one()

    ref_url = f"https://t.me/{settings.tg_bot_username}?start=ref_{user.ref_code}"

    return {
        "ref_code": user.ref_code,
        "ref_url": ref_url,
        "invited_count": invited_count,
        "earned_usd": f"{Decimal(earned_total):f}",
        "referral_rate_pct": 15,
    }
