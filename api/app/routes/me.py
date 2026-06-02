from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import telegram_user
from app.config import settings
from app.db import get_session
from app.models import CashbackEntry, ExchangeAccount, User, UserBalance, Withdrawal
from app.redis_client import redis as redis_client
from app.services.notifications import notify_event
from app.services.referrals import claim_pending_referral

router = APIRouter()


def _generate_ref_code() -> str:
    return secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:10]


async def _get_or_create_user(session: AsyncSession, tg_user: dict) -> User:
    tg_id = int(tg_user["id"])
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one_or_none()
    if user:
        # Освежаем профиль из initData: имя/фамилия/username могли смениться в
        # Telegram. Пишем только при изменении — функция вызывается на каждый
        # авторизованный запрос (/api/me и др.), лишних записей не делаем.
        new_first = tg_user.get("first_name")
        new_last = tg_user.get("last_name")
        new_username = tg_user.get("username")
        if (
            user.tg_first_name != new_first
            or user.tg_last_name != new_last
            or user.tg_username != new_username
        ):
            user.tg_first_name = new_first
            user.tg_last_name = new_last
            user.tg_username = new_username
            await session.commit()
        return user

    referrer_id = await claim_pending_referral(session, redis_client, tg_id)
    user = User(
        tg_id=tg_id,
        tg_username=tg_user.get("username"),
        tg_first_name=tg_user.get("first_name"),
        tg_last_name=tg_user.get("last_name"),
        language=(tg_user.get("language_code") or "ru")[:8],
        ref_code=_generate_ref_code(),
        referrer_id=referrer_id,
    )
    session.add(user)
    await session.flush()
    session.add(UserBalance(user_id=user.id))
    await session.commit()
    await session.refresh(user)

    if referrer_id is not None:
        referrer = await session.get(User, referrer_id)
        if referrer is not None:
            await notify_event(
                "referral.new",
                referrer.tg_id,
                {
                    "invitee_name": user.tg_first_name or user.tg_username or "Пользователь",
                    "invitee_username": user.tg_username,
                },
            )

    return user


@router.get("/api/me/stats")
async def get_my_stats(
    exchange: str | None = None,
    days: int = 30,
    tg_user: dict = Depends(telegram_user),
    session: AsyncSession = Depends(get_session),
):
    if days < 1 or days > 365:
        days = 30
    user = await _get_or_create_user(session, tg_user)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date()

    q = (
        select(CashbackEntry)
        .where(
            CashbackEntry.user_id == user.id,
            CashbackEntry.source_date >= cutoff,
        )
        .order_by(CashbackEntry.source_date.desc(), CashbackEntry.created_at.desc())
        .limit(200)
    )
    if exchange:
        q = q.where(CashbackEntry.exchange == exchange)
    entries = (await session.execute(q)).scalars().all()

    total_q = select(
        CashbackEntry.kind,
        func.coalesce(func.sum(CashbackEntry.amount_usd), 0),
    ).where(
        CashbackEntry.user_id == user.id,
        CashbackEntry.source_date >= cutoff,
    )
    if exchange:
        total_q = total_q.where(CashbackEntry.exchange == exchange)
    total_q = total_q.group_by(CashbackEntry.kind)
    by_kind = {k: Decimal(v) for k, v in (await session.execute(total_q)).all()}

    # Daily aggregate per exchange (для возможного графика).
    daily_q = (
        select(
            CashbackEntry.source_date,
            func.coalesce(func.sum(CashbackEntry.amount_usd), 0),
        )
        .where(
            CashbackEntry.user_id == user.id,
            CashbackEntry.source_date >= cutoff,
        )
        .group_by(CashbackEntry.source_date)
        .order_by(CashbackEntry.source_date.asc())
    )
    if exchange:
        daily_q = daily_q.where(CashbackEntry.exchange == exchange)
    daily_rows = (await session.execute(daily_q)).all()

    return {
        "period_days": days,
        "exchange": exchange,
        "total_cashback_usd": f"{sum(by_kind.values(), Decimal(0)):f}",
        "by_kind": {k: f"{v:f}" for k, v in by_kind.items()},
        "daily": [
            {"date": d.isoformat() if d else None, "amount_usd": f"{Decimal(v):f}"}
            for d, v in daily_rows
        ],
        "entries": [
            {
                "id": str(e.id),
                "exchange": e.exchange,
                "kind": e.kind,
                "amount_usd": f"{e.amount_usd:f}",
                "rate_applied": f"{e.rate_applied:f}" if e.rate_applied else None,
                "vip_tier_at_time": e.vip_tier_at_time,
                "source_date": e.source_date.isoformat() if e.source_date else None,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ],
    }


@router.get("/api/me")
async def get_me(
    tg_user: dict = Depends(telegram_user),
    session: AsyncSession = Depends(get_session),
):
    user = await _get_or_create_user(session, tg_user)
    balance = await session.get(UserBalance, user.id)
    accrued_total = balance.accrued_usd if balance else Decimal(0)
    paid_out_total = balance.paid_out_usd if balance else Decimal(0)

    reserved_total: Decimal = (
        await session.execute(
            select(func.coalesce(func.sum(Withdrawal.amount_usd), 0)).where(
                Withdrawal.user_id == user.id,
                Withdrawal.status.in_(["pending", "processing"]),
            )
        )
    ).scalar_one()
    available_total = accrued_total - paid_out_total - reserved_total

    # Per-exchange balances — считаются on-the-fly из cashback_entries / withdrawals.
    accrued_rows = (
        await session.execute(
            select(
                CashbackEntry.exchange,
                func.coalesce(func.sum(CashbackEntry.amount_usd), 0),
            )
            .where(CashbackEntry.user_id == user.id)
            .group_by(CashbackEntry.exchange)
        )
    ).all()
    paid_rows = (
        await session.execute(
            select(
                Withdrawal.exchange,
                func.coalesce(
                    func.sum(Withdrawal.amount_usd).filter(Withdrawal.status == "done"),
                    0,
                ),
                func.coalesce(
                    func.sum(Withdrawal.amount_usd).filter(
                        Withdrawal.status.in_(["pending", "processing"])
                    ),
                    0,
                ),
            )
            .where(Withdrawal.user_id == user.id)
            .group_by(Withdrawal.exchange)
        )
    ).all()

    per_exchange: dict[str, dict] = {}
    for ex, acc in accrued_rows:
        per_exchange.setdefault(ex, {"accrued": Decimal(0), "paid_out": Decimal(0), "reserved": Decimal(0)})
        per_exchange[ex]["accrued"] = Decimal(acc or 0)
    for ex, paid, pending in paid_rows:
        per_exchange.setdefault(ex, {"accrued": Decimal(0), "paid_out": Decimal(0), "reserved": Decimal(0)})
        per_exchange[ex]["paid_out"] = Decimal(paid or 0)
        per_exchange[ex]["reserved"] = Decimal(pending or 0)

    exchanges_result = await session.execute(
        select(ExchangeAccount).where(ExchangeAccount.user_id == user.id)
    )
    exchanges_list = list(exchanges_result.scalars())
    # Include exchange slugs from active connections too, even if balance=0.
    for ex_acc in exchanges_list:
        per_exchange.setdefault(
            ex_acc.exchange,
            {"accrued": Decimal(0), "paid_out": Decimal(0), "reserved": Decimal(0)},
        )

    balances = [
        {
            "exchange": ex,
            "accrued_usd": f"{vals['accrued']:f}",
            "paid_out_usd": f"{vals['paid_out']:f}",
            "reserved_usd": f"{vals['reserved']:f}",
            "available_usd": f"{vals['accrued'] - vals['paid_out'] - vals['reserved']:f}",
        }
        for ex, vals in per_exchange.items()
    ]

    exchanges = [
        {"exchange": ex.exchange, "uid": ex.exchange_uid, "status": ex.status}
        for ex in exchanges_list
    ]

    return {
        "user": {
            "id": str(user.id),
            "tg_id": user.tg_id,
            "tg_username": user.tg_username,
            "name": user.tg_first_name or user.tg_username or "User",
            "ref_code": user.ref_code,
            "vip_tier": user.vip_tier,
            "language": user.language,
        },
        # Суммарный баланс (для VIP-прогресса и общей статистики).
        "balance": {
            "accrued_usd": f"{accrued_total:f}",
            "paid_out_usd": f"{paid_out_total:f}",
            "reserved_usd": f"{reserved_total:f}",
            "available_usd": f"{available_total:f}",
        },
        # Балансы per-биржа — основное, что показывает UI.
        "balances": balances,
        "exchanges": exchanges,
        "withdrawal": {
            "min_usd": settings.withdrawal_min_usd,
            "daily_limit_usd": settings.withdrawal_daily_limit_usd,
            "monthly_limit_usd": settings.withdrawal_monthly_limit_usd,
            "cooldown_minutes": settings.withdrawal_cooldown_minutes,
        },
    }
