"""Basic anti-fraud rules.

Runs daily after the commission sync. Signals are written to audit_log with
action='fraud.*'.

Rules:
  • low_fee_ratio — user with volume > THRESHOLD over the last 30 days but an
                    effective fee rate (commission/volume) below LOW_FEE_RATIO.
                    Classic wash-trading signal; the user's withdrawals are held.
  • self_referral — referrer and referee withdraw to the same TRC-20 address —
                    very likely one person on two accounts; both are held.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import AuditLog, DailyUserCommission, User, Withdrawal

log = logging.getLogger("antifraud")

WINDOW_DAYS = 30
THRESHOLD_VOLUME_USD = Decimal("1000")
LOW_FEE_RATIO = Decimal("0.0001")  # 0.01% — below normal even for maker
RERUN_COOLDOWN_HOURS = 12  # don't flag the same user twice per cooldown


async def _recent_flag_exists(session: AsyncSession, user_id, rule: str, hours: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = select(func.count(AuditLog.id)).where(
        AuditLog.action == f"fraud.{rule}",
        AuditLog.user_id == user_id,
        AuditLog.created_at >= cutoff,
    )
    return ((await session.execute(q)).scalar_one() or 0) > 0


async def run_fraud_check() -> dict:
    """Scan recent volume/fee ratios and write audit_log entries for outliers."""
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=WINDOW_DAYS - 1)
    flagged_users = 0
    flagged_self_referrals = 0

    async with SessionLocal() as session:
        # Per-user aggregates over the window.
        per_user_q = (
            select(
                DailyUserCommission.user_id,
                func.coalesce(func.sum(DailyUserCommission.total_volume_usd), 0),
                func.coalesce(func.sum(DailyUserCommission.total_commission_usd), 0),
            )
            .where(DailyUserCommission.date >= cutoff)
            .group_by(DailyUserCommission.user_id)
        )
        rows = (await session.execute(per_user_q)).all()

        for user_id, total_volume, total_commission in rows:
            volume = Decimal(total_volume or 0)
            commission = Decimal(total_commission or 0)
            if volume < THRESHOLD_VOLUME_USD:
                continue
            effective = commission / volume
            if effective >= LOW_FEE_RATIO:
                continue

            # Hold the wash-trader's withdrawals; accrual continues, payout is
            # blocked until a manual review clears it. Idempotent (audit cooldown).
            held = await session.get(User, user_id)
            if held is not None and not held.fraud_hold:
                held.fraud_hold = True
                held.fraud_hold_reason = "wash_trade_low_fee_ratio"

            if await _recent_flag_exists(session, user_id, "low_fee_ratio", RERUN_COOLDOWN_HOURS):
                continue

            session.add(
                AuditLog(
                    user_id=user_id,
                    action="fraud.low_fee_ratio",
                    extra={
                        "volume_usd": f"{volume:f}",
                        "commission_usd": f"{commission:f}",
                        "effective_rate": f"{effective:.8f}",
                        "window_days": WINDOW_DAYS,
                    },
                )
            )
            flagged_users += 1

        # Self-referral: referrer and referee withdraw to the SAME TRC-20 address —
        # with high probability one person on two accounts.
        addr_rows = (
            await session.execute(
                select(Withdrawal.user_id, Withdrawal.destination_value).where(
                    Withdrawal.destination_type == "trc20",
                    Withdrawal.status != "failed",
                )
            )
        ).all()
        addr_to_users: dict[str, set] = {}
        for uid, addr in addr_rows:
            if addr:
                addr_to_users.setdefault(addr, set()).add(uid)

        for addr, uids in addr_to_users.items():
            if len(uids) < 2:
                continue
            for uid in uids:
                u = await session.get(User, uid)
                if u is None or u.referrer_id is None or u.referrer_id not in uids:
                    continue
                referrer = await session.get(User, u.referrer_id)
                for victim in (u, referrer):
                    if victim is not None and not victim.fraud_hold:
                        victim.fraud_hold = True
                        victim.fraud_hold_reason = "self_referral_shared_payout"
                if not await _recent_flag_exists(session, uid, "self_referral", 24):
                    session.add(
                        AuditLog(
                            user_id=uid,
                            action="fraud.self_referral",
                            extra={"referrer_id": str(u.referrer_id), "shared_trc20": addr},
                        )
                    )
                    flagged_self_referrals += 1

        await session.commit()

    summary = {
        "status": "ok",
        "flagged_users": flagged_users,
        "flagged_self_referrals": flagged_self_referrals,
        "window_days": WINDOW_DAYS,
    }
    log.info("fraud_check done: %s", summary)
    return summary
