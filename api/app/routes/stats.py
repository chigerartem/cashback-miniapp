"""Public showcase endpoints: global stats, recent withdrawals, leaderboard.

Single-tenant: figures are computed across all users. When the database is
still thin (a fresh deploy), deterministic demo data is served instead so the
Mini App never looks empty — toggled by settings.demo_social_proof.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import (
    CashbackEntry,
    DailyUserCommission,
    ExchangeAccount,
    User,
    Withdrawal,
)
from app.services.fake_leaderboard import generate as generate_fake_leaderboard
from app.services.fake_withdrawals import generate as generate_fake_withdrawals

# Below these counts the live showcase would look empty, so we serve demo data.
REAL_WITHDRAWALS_THRESHOLD = 5
REAL_LEADERBOARD_THRESHOLD = 10
REAL_TRADERS_THRESHOLD = 5
DEMO_SEED = "demo"

# Plausible (not real) figures for the home header on a fresh deploy.
DEMO_GLOBAL_STATS = {
    "total_paid_out_usd": "184213.50",
    "total_traders": 2417,
    "volume_30d_usd": "5120000",
}

router = APIRouter(prefix="/api", tags=["stats"])


def _mask_uid(uid: str) -> str:
    if not uid:
        return "***"
    if len(uid) <= 4:
        return "***" + uid[-1:]
    return uid[:2] + "***" + uid[-2:]


def _mask_name(first: str | None, last: str | None, username: str | None) -> str:
    if first:
        if last:
            return f"{first} {last[0].upper()}."
        return first
    if username:
        return f"@{username[:3]}***"
    return "Аноним"


@router.get("/stats/global")
async def stats_global(session: AsyncSession = Depends(get_session)):
    total_paid_out: Decimal = (
        await session.execute(
            select(func.coalesce(func.sum(Withdrawal.amount_usd), 0)).where(
                Withdrawal.status == "done"
            )
        )
    ).scalar_one()
    total_traders: int = (
        await session.execute(
            select(func.count(func.distinct(ExchangeAccount.user_id))).where(
                ExchangeAccount.status == "active"
            )
        )
    ).scalar_one()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).date()
    volume_30d: Decimal = (
        await session.execute(
            select(func.coalesce(func.sum(DailyUserCommission.total_volume_usd), 0)).where(
                DailyUserCommission.date >= cutoff
            )
        )
    ).scalar_one()

    if settings.demo_social_proof and int(total_traders) < REAL_TRADERS_THRESHOLD:
        return DEMO_GLOBAL_STATS

    return {
        "total_paid_out_usd": f"{Decimal(total_paid_out):f}",
        "total_traders": int(total_traders),
        "volume_30d_usd": f"{Decimal(volume_30d):f}",
    }


@router.get("/stats/recent_withdrawals")
async def recent_withdrawals(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(
                Withdrawal.id,
                Withdrawal.amount_usd,
                Withdrawal.destination_type,
                Withdrawal.destination_value,
                Withdrawal.completed_at,
            )
            .where(Withdrawal.status == "done")
            .order_by(Withdrawal.completed_at.desc())
            .limit(limit)
        )
    ).all()

    if len(rows) >= REAL_WITHDRAWALS_THRESHOLD or not settings.demo_social_proof:
        return [
            {
                "id": str(r.id),
                "amount_usd": f"{Decimal(r.amount_usd):f}",
                "destination_type": r.destination_type,
                "destination_masked": _mask_uid(r.destination_value),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in rows
        ]

    return generate_fake_withdrawals(DEMO_SEED, limit=limit)


@router.get("/leaderboard")
async def leaderboard(
    period: str = Query("all", pattern="^(all|30d)$"),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    q = (
        select(
            User.tg_first_name,
            User.tg_last_name,
            User.tg_username,
            User.vip_tier,
            func.coalesce(func.sum(CashbackEntry.amount_usd), 0).label("earned"),
        )
        .join(CashbackEntry, CashbackEntry.user_id == User.id)
        .where(CashbackEntry.kind.in_(["self", "referral"]))
    )
    if period == "30d":
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        q = q.where(CashbackEntry.created_at >= cutoff)
    q = (
        q.group_by(
            User.id, User.tg_first_name, User.tg_last_name, User.tg_username, User.vip_tier
        )
        .order_by(func.sum(CashbackEntry.amount_usd).desc())
        .limit(limit)
    )
    rows = (await session.execute(q)).all()

    if len(rows) >= REAL_LEADERBOARD_THRESHOLD or not settings.demo_social_proof:
        return [
            {
                "rank": i + 1,
                "name": _mask_name(r.tg_first_name, r.tg_last_name, r.tg_username),
                "vip_tier": r.vip_tier,
                "earned_usd": f"{Decimal(r.earned):f}",
            }
            for i, r in enumerate(rows)
        ]

    return generate_fake_leaderboard(DEMO_SEED, period=period, limit=limit)
