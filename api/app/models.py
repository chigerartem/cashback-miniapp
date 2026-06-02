from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    tg_username: Mapped[str | None] = mapped_column(Text, nullable=True)
    tg_first_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    tg_last_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="ru", nullable=False)
    ref_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    referrer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    vip_tier: Mapped[str] = mapped_column(String(16), default="bronze", nullable=False)
    total_paid_out_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal(0), nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    block_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # fraud_hold blocks withdrawals only (not the whole account). Set by the
    # anti-fraud worker, cleared manually after review.
    fraud_hold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fraud_hold_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ExchangeAccount(Base):
    __tablename__ = "exchange_accounts"
    __table_args__ = (UniqueConstraint("exchange", "exchange_uid", name="uq_exchange_uid"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange_uid: Mapped[str] = mapped_column(Text, nullable=False)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DailyUserCommission(Base):
    """Per-(user, date) aggregate of BingX broker commissions (our income)."""

    __tablename__ = "daily_user_commissions"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    spot_volume_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal(0))
    swap_volume_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal(0))
    std_volume_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal(0))
    copy_volume_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal(0))
    mt5_volume_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal(0))
    total_volume_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal(0))
    spot_commission_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal(0))
    swap_commission_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal(0))
    std_commission_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal(0))
    copy_commission_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal(0))
    mt5_commission_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal(0))
    total_commission_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal(0))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DailyBinanceCommission(Base):
    """Per-(user, date) aggregate of Binance rebates (apiReferral / Binance Link).

    Kept in its own table so it never touches the BingX daily_user_commissions
    stream. total_commission_usd is our income (rebate) for the user that day.
    """

    __tablename__ = "daily_binance_commissions"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    total_volume_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal(0))
    total_commission_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal(0))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DailyBitgetCommission(Base):
    """Per-(user, date) aggregate of Bitget rebates (agent/affiliate)."""

    __tablename__ = "daily_bitget_commissions"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    total_volume_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal(0))
    total_commission_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal(0))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DailyMexcCommission(Base):
    """Per-(user, date) aggregate of MEXC rebates (affiliate/broker)."""

    __tablename__ = "daily_mexc_commissions"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    total_volume_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal(0))
    total_commission_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal(0))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DailyBydfiCommission(Base):
    """Per-(user, date) aggregate of BYDFi rebates (affiliate/agent)."""

    __tablename__ = "daily_bydfi_commissions"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    total_volume_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal(0))
    total_commission_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal(0))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CashbackEntry(Base):
    __tablename__ = "cashback_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False, default="bingx", server_default="bingx", index=True)
    source_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # 'self' | 'referral'
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    rate_applied: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    vip_tier_at_time: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class UserBalance(Base):
    __tablename__ = "user_balances"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    accrued_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal(0), nullable=False)
    paid_out_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal(0), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False, default="bingx", server_default="bingx", index=True)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    destination_type: Mapped[str] = mapped_column(String(16), nullable=False)  # 'bingx_uid' | 'trc20'
    destination_value: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    tx_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
