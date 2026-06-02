"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-02

Single-tenant cashback schema: users, exchange accounts, per-exchange daily
commissions, cashback entries, balances, withdrawals, audit log.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("tg_username", sa.Text(), nullable=True),
        sa.Column("tg_first_name", sa.Text(), nullable=True),
        sa.Column("tg_last_name", sa.Text(), nullable=True),
        sa.Column("language", sa.String(8), nullable=False, server_default="ru"),
        sa.Column("ref_code", sa.String(32), nullable=False),
        sa.Column("referrer_id", UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("vip_tier", sa.String(16), nullable=False, server_default="bronze"),
        sa.Column("total_paid_out_usd", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("block_reason", sa.Text(), nullable=True),
        sa.Column("fraud_hold", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("fraud_hold_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_users_tg_id", "users", ["tg_id"], unique=True)
    op.create_index("ix_users_ref_code", "users", ["ref_code"], unique=True)
    op.create_index("ix_users_referrer_id", "users", ["referrer_id"])

    op.create_table(
        "exchange_accounts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("exchange_uid", sa.Text(), nullable=False),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("exchange", "exchange_uid", name="uq_exchange_uid"),
    )
    op.create_index("ix_exchange_accounts_user_id", "exchange_accounts", ["user_id"])

    op.create_table(
        "daily_user_commissions",
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("spot_volume_usd", sa.Numeric(20, 8), server_default="0"),
        sa.Column("swap_volume_usd", sa.Numeric(20, 8), server_default="0"),
        sa.Column("std_volume_usd", sa.Numeric(20, 8), server_default="0"),
        sa.Column("copy_volume_usd", sa.Numeric(20, 8), server_default="0"),
        sa.Column("mt5_volume_usd", sa.Numeric(20, 8), server_default="0"),
        sa.Column("total_volume_usd", sa.Numeric(20, 8), server_default="0"),
        sa.Column("spot_commission_usd", sa.Numeric(18, 8), server_default="0"),
        sa.Column("swap_commission_usd", sa.Numeric(18, 8), server_default="0"),
        sa.Column("std_commission_usd", sa.Numeric(18, 8), server_default="0"),
        sa.Column("copy_commission_usd", sa.Numeric(18, 8), server_default="0"),
        sa.Column("mt5_commission_usd", sa.Numeric(18, 8), server_default="0"),
        sa.Column("total_commission_usd", sa.Numeric(18, 8), server_default="0"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_daily_user_commissions_date", "daily_user_commissions", ["date"])

    for ex in ("binance", "bitget", "mexc", "bydfi"):
        table = f"daily_{ex}_commissions"
        op.create_table(
            table,
            sa.Column("user_id", UUID, sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("date", sa.Date(), primary_key=True),
            sa.Column("total_volume_usd", sa.Numeric(20, 8), server_default="0"),
            sa.Column("total_commission_usd", sa.Numeric(18, 8), server_default="0"),
            sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        )
        op.create_index(f"ix_{table}_date", table, ["date"])

    op.create_table(
        "cashback_entries",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False, server_default="bingx"),
        sa.Column("source_date", sa.Date(), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("amount_usd", sa.Numeric(18, 8), nullable=False),
        sa.Column("rate_applied", sa.Numeric(6, 4), nullable=True),
        sa.Column("vip_tier_at_time", sa.String(16), nullable=True),
        sa.Column("source_user_id", UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_cashback_entries_user_id", "cashback_entries", ["user_id"])
    op.create_index("ix_cashback_entries_exchange", "cashback_entries", ["exchange"])
    op.create_index("ix_cashback_entries_created_at", "cashback_entries", ["created_at"])

    op.create_table(
        "user_balances",
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("accrued_usd", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("paid_out_usd", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )

    op.create_table(
        "withdrawals",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False, server_default="bingx"),
        sa.Column("amount_usd", sa.Numeric(18, 8), nullable=False),
        sa.Column("destination_type", sa.String(16), nullable=False),
        sa.Column("destination_value", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("tx_hash", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_withdrawals_user_id", "withdrawals", ["user_id"])
    op.create_index("ix_withdrawals_exchange", "withdrawals", ["exchange"])
    op.create_index("ix_withdrawals_status", "withdrawals", ["status"])
    op.create_index("ix_withdrawals_created_at", "withdrawals", ["created_at"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("extra", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("withdrawals")
    op.drop_table("user_balances")
    op.drop_table("cashback_entries")
    for ex in ("bydfi", "mexc", "bitget", "binance"):
        op.drop_table(f"daily_{ex}_commissions")
    op.drop_table("daily_user_commissions")
    op.drop_table("exchange_accounts")
    op.drop_table("users")
