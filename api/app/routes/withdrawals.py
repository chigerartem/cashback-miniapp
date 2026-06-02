"""User withdrawal endpoints."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import telegram_user
from app.config import settings
from app.db import get_session
from app.models import CashbackEntry, ExchangeAccount, User, UserBalance, Withdrawal

router = APIRouter(prefix="/api/withdrawals", tags=["withdrawals"])

TRC20_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
BINGX_UID_RE = re.compile(r"^[0-9]{3,32}$")


class CreateWithdrawal(BaseModel):
    amount_usd: Decimal = Field(gt=0)
    exchange: str = Field(default="bingx", pattern=r"^[a-z0-9_-]{2,32}$")
    destination_type: str = Field(pattern=r"^(bingx_uid|trc20)$")
    destination_value: str = Field(min_length=3, max_length=128)


async def _current_user(session: AsyncSession, tg_user: dict) -> User:
    tg_id = int(tg_user["id"])
    user = (
        await session.execute(select(User).where(User.tg_id == tg_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Профиль не найден")
    if user.is_blocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Аккаунт заблокирован")
    return user


async def _available_balance(session: AsyncSession, user: User) -> Decimal:
    """Общий доступный баланс юзера: accrued - paid_out - sum(pending+processing)."""
    bal = await session.get(UserBalance, user.id)
    accrued = bal.accrued_usd if bal else Decimal("0")
    paid_out = bal.paid_out_usd if bal else Decimal("0")
    reserved: Decimal = (
        await session.execute(
            select(func.coalesce(func.sum(Withdrawal.amount_usd), 0)).where(
                Withdrawal.user_id == user.id,
                Withdrawal.status.in_(["pending", "processing"]),
            )
        )
    ).scalar_one()
    return accrued - paid_out - reserved


async def _available_balance_exchange(
    session: AsyncSession, user: User, exchange: str
) -> Decimal:
    """Доступный баланс на конкретной бирже."""
    accrued: Decimal = (
        await session.execute(
            select(func.coalesce(func.sum(CashbackEntry.amount_usd), 0)).where(
                CashbackEntry.user_id == user.id,
                CashbackEntry.exchange == exchange,
            )
        )
    ).scalar_one()
    paid_out: Decimal = (
        await session.execute(
            select(func.coalesce(func.sum(Withdrawal.amount_usd), 0)).where(
                Withdrawal.user_id == user.id,
                Withdrawal.exchange == exchange,
                Withdrawal.status == "done",
            )
        )
    ).scalar_one()
    reserved: Decimal = (
        await session.execute(
            select(func.coalesce(func.sum(Withdrawal.amount_usd), 0)).where(
                Withdrawal.user_id == user.id,
                Withdrawal.exchange == exchange,
                Withdrawal.status.in_(["pending", "processing"]),
            )
        )
    ).scalar_one()
    return Decimal(accrued or 0) - Decimal(paid_out or 0) - Decimal(reserved or 0)


def _validate_destination(d_type: str, d_value: str) -> None:
    if d_type == "trc20":
        if not TRC20_RE.match(d_value):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Адрес TRC-20 указан в неверном формате",
            )
    elif d_type == "bingx_uid":
        if not BINGX_UID_RE.match(d_value):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "BingX UID должен состоять только из цифр",
            )


@router.post("")
async def create_withdrawal(
    body: CreateWithdrawal,
    tg_user: dict = Depends(telegram_user),
    session: AsyncSession = Depends(get_session),
):
    user = await _current_user(session, tg_user)
    if user.fraud_hold:
        # Hold от антифрода: начисления идут, но вывод заблокирован до ручной проверки.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Выводы временно приостановлены: аккаунт на проверке. Напишите в поддержку.",
        )
    _validate_destination(body.destination_type, body.destination_value)

    # Сериализуем создание выводов одного юзера: row-lock на его UserBalance.
    # Иначе два параллельных запроса оба проходят check-then-insert (cooldown,
    # дневной/месячный лимит, available) и выводят сверх баланса.
    # Lock держится до commit транзакции запроса; второй запрос ждёт первого
    # и затем видит его pending-вывод в reserved.
    await session.get(UserBalance, user.id, with_for_update=True)

    amount = body.amount_usd
    min_usd = Decimal(str(settings.withdrawal_min_usd))
    if amount < min_usd:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Минимальная сумма вывода — ${min_usd}",
        )

    if body.destination_type == "bingx_uid":
        owned = (
            await session.execute(
                select(ExchangeAccount).where(
                    ExchangeAccount.user_id == user.id,
                    ExchangeAccount.exchange == "bingx",
                    ExchangeAccount.exchange_uid == body.destination_value,
                    ExchangeAccount.status == "active",
                )
            )
        ).scalar_one_or_none()
        if owned is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Указанный BingX UID не привязан к вашему аккаунту",
            )

    # Проверка что юзер реально привязан к бирже, с которой выводит.
    src_account = (
        await session.execute(
            select(ExchangeAccount).where(
                ExchangeAccount.user_id == user.id,
                ExchangeAccount.exchange == body.exchange,
                ExchangeAccount.status == "active",
            )
        )
    ).scalar_one_or_none()
    if src_account is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"К вашему аккаунту не привязана активная биржа {body.exchange.upper()}",
        )

    now = datetime.now(timezone.utc)
    cooldown_cutoff = now - timedelta(minutes=settings.withdrawal_cooldown_minutes)
    recent = (
        await session.execute(
            select(Withdrawal.created_at)
            .where(
                Withdrawal.user_id == user.id,
                Withdrawal.created_at >= cooldown_cutoff,
                Withdrawal.status != "failed",
            )
            .order_by(Withdrawal.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if recent is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Слишком частые запросы. Подождите "
            f"{settings.withdrawal_cooldown_minutes} минут между выводами.",
        )

    day_cutoff = now - timedelta(days=1)
    month_cutoff = now - timedelta(days=30)
    day_sum: Decimal = (
        await session.execute(
            select(func.coalesce(func.sum(Withdrawal.amount_usd), 0)).where(
                Withdrawal.user_id == user.id,
                Withdrawal.created_at >= day_cutoff,
                Withdrawal.status != "failed",
            )
        )
    ).scalar_one()
    month_sum: Decimal = (
        await session.execute(
            select(func.coalesce(func.sum(Withdrawal.amount_usd), 0)).where(
                Withdrawal.user_id == user.id,
                Withdrawal.created_at >= month_cutoff,
                Withdrawal.status != "failed",
            )
        )
    ).scalar_one()
    daily_limit = Decimal(str(settings.withdrawal_daily_limit_usd))
    monthly_limit = Decimal(str(settings.withdrawal_monthly_limit_usd))
    if day_sum + amount > daily_limit:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Превышен дневной лимит вывода ${daily_limit}",
        )
    if month_sum + amount > monthly_limit:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Превышен месячный лимит вывода ${monthly_limit}",
        )

    available = await _available_balance_exchange(session, user, body.exchange)
    if amount > available:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Доступно к выводу с {body.exchange.upper()}: ${available:f}",
        )

    w = Withdrawal(
        user_id=user.id,
        exchange=body.exchange,
        amount_usd=amount,
        destination_type=body.destination_type,
        destination_value=body.destination_value,
        status="pending",
    )
    session.add(w)
    await session.commit()
    await session.refresh(w)

    return {
        "id": str(w.id),
        "status": w.status,
        "amount_usd": f"{w.amount_usd:f}",
        "created_at": w.created_at.isoformat(),
    }


@router.get("")
async def list_withdrawals(
    limit: int = 50,
    tg_user: dict = Depends(telegram_user),
    session: AsyncSession = Depends(get_session),
):
    user = await _current_user(session, tg_user)
    rows = (
        await session.execute(
            select(Withdrawal)
            .where(Withdrawal.user_id == user.id)
            .order_by(Withdrawal.created_at.desc())
            .limit(min(max(limit, 1), 200))
        )
    ).scalars().all()
    return [
        {
            "id": str(w.id),
            "exchange": w.exchange,
            "amount_usd": f"{w.amount_usd:f}",
            "destination_type": w.destination_type,
            "destination_masked": _mask(w.destination_value),
            "status": w.status,
            "tx_hash": w.tx_hash,
            "failure_reason": w.failure_reason,
            "created_at": w.created_at.isoformat(),
            "completed_at": w.completed_at.isoformat() if w.completed_at else None,
        }
        for w in rows
    ]


@router.get("/limits")
async def get_limits(
    tg_user: dict = Depends(telegram_user),
    session: AsyncSession = Depends(get_session),
):
    user = await _current_user(session, tg_user)
    available = await _available_balance(session, user)
    return {
        "available_usd": f"{available:f}",
        "min_usd": settings.withdrawal_min_usd,
        "daily_limit_usd": settings.withdrawal_daily_limit_usd,
        "monthly_limit_usd": settings.withdrawal_monthly_limit_usd,
        "cooldown_minutes": settings.withdrawal_cooldown_minutes,
    }


def _mask(value: str) -> str:
    if not value:
        return "***"
    if len(value) <= 6:
        return "***" + value[-2:]
    return value[:4] + "***" + value[-4:]
