"""Seed deterministic demo data so a fresh deploy isn't empty.

Run inside the api container:
    docker compose exec api python -m app.seed_demo

Creates demo users, BingX exchange accounts and daily commissions, runs the
real accrual engine, and marks a few withdrawals as done — enough for the
public showcase (global stats, leaderboard, recent withdrawals) to serve real
figures instead of the demo fallback. Safe to run repeatedly.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.db import SessionLocal
from app.models import DailyUserCommission, ExchangeAccount, User, UserBalance, Withdrawal
from app.services.cashback import accrue_for_date

DEMO_TG_BASE = 900_000_000
TIERS = ["vip", "diamond", "platinum", "gold", "gold", "silver", "silver", "bronze", "bronze", "bronze"]
NAMES: list[tuple[str, str | None]] = [
    ("Дмитрий", "dmitry_k"), ("Анна", None), ("Sergei", "sergei_l"), ("Виктор", "moon_trader"),
    ("Мария", None), ("Aleksandr", "whale88"), ("Игорь", "hodl_master"), ("Екатерина", None),
    ("Roman", "day_trade"), ("Павел", None), ("Наталья", "scalp_q"), ("Олег", None),
    ("Юлия", "yulia_fx"), ("Денис", None), ("Светлана", "sveta_t"), ("Артур", "art_trades"),
    ("Кирилл", None), ("Алина", "alina_btc"), ("Максим", "max_perp"), ("Ольга", None),
    ("Григорий", "greg_x"), ("Тимур", None), ("Вероника", "nika_v"), ("Степан", "stp"),
    ("Лариса", None),
]


async def seed() -> None:
    async with SessionLocal() as session:
        already = (
            await session.execute(select(User).where(User.tg_id == DEMO_TG_BASE + 1))
        ).scalar_one_or_none()
        if already:
            print("demo data already present — nothing to do")
            return

        users: list[User] = []
        for i, (first, uname) in enumerate(NAMES, start=1):
            u = User(
                tg_id=DEMO_TG_BASE + i,
                tg_username=uname,
                tg_first_name=first,
                ref_code=f"seed{i:04d}",
                vip_tier=TIERS[(i - 1) % len(TIERS)],
            )
            session.add(u)
            users.append(u)
        await session.flush()

        # Every fourth user was invited by the first user (populates referral cashback).
        for i, u in enumerate(users):
            if i > 0 and i % 4 == 0:
                u.referrer_id = users[0].id

        today = datetime.now(timezone.utc).date()
        for i, u in enumerate(users, start=1):
            session.add(
                ExchangeAccount(
                    user_id=u.id, exchange="bingx", exchange_uid=f"7{u.tg_id}",
                    status="active", invited_at=datetime.now(timezone.utc),
                )
            )
            session.add(UserBalance(user_id=u.id))
            for d in range(1, 6):  # last 5 days
                commission = Decimal("0.5") + Decimal(i % 7)
                session.add(
                    DailyUserCommission(
                        user_id=u.id,
                        date=today - timedelta(days=d),
                        total_volume_usd=commission * Decimal(4000),  # fee ratio safely > anti-fraud floor
                        total_commission_usd=commission,
                    )
                )
        await session.commit()

        for d in range(1, 6):
            await accrue_for_date(session, today - timedelta(days=d), exchange="bingx")

        # A handful of completed withdrawals so the "recent withdrawals" feed is real.
        for i, u in enumerate(users[:8]):
            amount = Decimal("20") + Decimal(i * 17)
            session.add(
                Withdrawal(
                    user_id=u.id, exchange="bingx", amount_usd=amount,
                    destination_type="trc20", destination_value=f"TDemo{i:033d}",
                    status="done", completed_at=datetime.now(timezone.utc) - timedelta(hours=i + 1),
                )
            )
            bal = await session.get(UserBalance, u.id)
            if bal is not None:
                bal.paid_out_usd = (bal.paid_out_usd or Decimal(0)) + amount
        await session.commit()

        print(f"seeded {len(users)} demo users, 5 days of commissions, 8 withdrawals")


if __name__ == "__main__":
    asyncio.run(seed())
