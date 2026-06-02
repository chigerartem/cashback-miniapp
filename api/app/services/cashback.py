"""Cashback engine — recompute accruals for a date.

From the per-exchange daily commissions it produces two kinds of entries:
  • self     — to the user:    fee_paid_total * (user_base_rate + VIP bonus)
  • referral — to the inviter: 15% of the user's self cashback

Idempotent: re-running for the same (exchange, date) deletes that exchange's
existing cashback_entries for the day and recomputes them with the current
economics / tiers.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date as date_cls
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CashbackEntry,
    DailyBinanceCommission,
    DailyBitgetCommission,
    DailyBydfiCommission,
    DailyMexcCommission,
    DailyUserCommission,
    User,
    UserBalance,
)
from app.services.cashback_math import (
    REFERRAL_RATE,
    broker_rate_for,
    compute_split,
    tier_for_paid_out,
    user_base_rate_for,
)

log = logging.getLogger("cashback")

__all__ = [
    "accrue_for_date",
    "compute_split",
    "tier_for_paid_out",
    "REFERRAL_RATE",
]


async def accrue_for_date(
    session: AsyncSession,
    target_date: date_cls,
    exchange: str = "bingx",
    broker_rate: Decimal | None = None,
) -> dict:
    """Recompute cashback_entries and balances for all users active on ``target_date``.

    ``exchange`` selects the daily-commission source table (each exposes
    ``.user_id`` and ``.total_commission_usd``). ``broker_rate`` is our share of
    the referral's fee on that exchange: BingX comes from ``cashback_math``,
    other exchanges pass it in from config. Returns a summary dict for logging.
    """
    user_base_rate = user_base_rate_for(exchange)
    if broker_rate is None:
        broker_rate = broker_rate_for(exchange)
    if broker_rate is None or broker_rate <= 0:
        raise ValueError(
            f"accrue_for_date: no broker_rate for exchange {exchange!r} "
            "(set the matching *_rebate_rate in config)"
        )

    # Advisory xact-lock per (exchange, date): serialises concurrent accrual runs
    # (nightly cron + midday safety + manual). Without it two delete-then-reinsert
    # passes overlap → duplicate cashback_entries and double-counted balances.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"cashback_accrue:{exchange}:{target_date.isoformat()}"},
    )

    _source_by_exchange = {
        "binance": DailyBinanceCommission,
        "bitget": DailyBitgetCommission,
        "mexc": DailyMexcCommission,
        "bydfi": DailyBydfiCommission,
    }
    source = _source_by_exchange.get(exchange, DailyUserCommission)
    daily_rows = (
        await session.execute(select(source).where(source.date == target_date))
    ).scalars().all()

    old_entries = (
        await session.execute(
            select(CashbackEntry).where(
                CashbackEntry.source_date == target_date,
                CashbackEntry.exchange == exchange,
            )
        )
    ).scalars().all()

    user_delta: dict = defaultdict(lambda: Decimal("0"))

    for e in old_entries:
        user_delta[e.user_id] -= e.amount_usd
        await session.delete(e)
    await session.flush()

    entries_created = 0
    skipped_zero = 0

    for dc in daily_rows:
        broker_received: Decimal = dc.total_commission_usd or Decimal("0")
        if broker_received <= 0:
            skipped_zero += 1
            continue

        user = await session.get(User, dc.user_id)
        if user is None or user.is_blocked:
            log.warning("skip user_id=%s (missing or blocked)", dc.user_id)
            continue

        referrer = None
        if user.referrer_id:
            referrer = await session.get(User, user.referrer_id)
            if referrer is None or referrer.is_blocked:
                referrer = None

        split = compute_split(
            broker_received=broker_received,
            vip_tier=user.vip_tier,
            has_referrer=referrer is not None,
            user_base_rate=user_base_rate,
            broker_rate=broker_rate,
        )

        session.add(
            CashbackEntry(
                user_id=user.id,
                exchange=exchange,
                source_date=target_date,
                kind="self",
                amount_usd=split.user_cb,
                rate_applied=split.rate_applied,
                vip_tier_at_time=user.vip_tier,
            )
        )
        user_delta[user.id] += split.user_cb
        entries_created += 1

        if split.referral_cb > 0 and referrer is not None:
            session.add(
                CashbackEntry(
                    user_id=referrer.id,
                    exchange=exchange,
                    source_date=target_date,
                    kind="referral",
                    amount_usd=split.referral_cb,
                    rate_applied=REFERRAL_RATE,
                    source_user_id=user.id,
                )
            )
            user_delta[referrer.id] += split.referral_cb
            entries_created += 1

    await session.flush()

    for uid, delta in user_delta.items():
        if delta == 0:
            continue
        bal = await session.get(UserBalance, uid)
        if bal is None:
            bal = UserBalance(user_id=uid, accrued_usd=Decimal("0"))
            session.add(bal)
            await session.flush()
        bal.accrued_usd = (bal.accrued_usd or Decimal("0")) + delta

    await session.commit()

    summary = {
        "date": target_date.isoformat(),
        "daily_rows": len(daily_rows),
        "old_entries_removed": len(old_entries),
        "entries_created": entries_created,
        "skipped_zero": skipped_zero,
        "users_touched": len(user_delta),
    }
    log.info("accrue_for_date %s", summary)
    return summary
