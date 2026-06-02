"""Pure cashback math — no DB dependencies, tested in isolation.

Imported by `cashback.py` (which adds DB orchestration) and by tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

BROKER_RATE = Decimal("0.50")          # доля комиссии, которую BingX отдаёт нам (дефолт)
USER_BASE_RATE = Decimal("0.30")       # базовый % юзеру от его fee (дефолт = BingX)
REFERRAL_RATE = Decimal("0.15")        # % рефереру от self юзера

# Per-exchange ставки. user_base — сколько юзеру от его fee (до VIP-бонуса).
# broker — какую долю fee биржа отдаёт нам (нужно, чтобы из нашей комиссии
# восстановить полный fee юзера). Для Binance broker берётся из config
# (binance_rebate_rate), т.к. зависит от ставки Binance Link.
USER_BASE_RATE_BY_EXCHANGE: dict[str, Decimal] = {
    "bingx": Decimal("0.30"),
    "binance": Decimal("0.05"),
    "bitget": Decimal("0.10"),
    "mexc": Decimal("0.30"),    # MEXC даёт нам 50% (spot+futures) → юзеру 30%, как BingX
    "bydfi": Decimal("0.35"),   # BYDFi даёт нам 50% spot / 60% swap → юзеру 35%
}
BROKER_RATE_BY_EXCHANGE: dict[str, Decimal] = {
    "bingx": Decimal("0.50"),
}


def user_base_rate_for(exchange: str) -> Decimal:
    return USER_BASE_RATE_BY_EXCHANGE.get(exchange, USER_BASE_RATE)


def broker_rate_for(exchange: str) -> Decimal | None:
    """None → ставка не задана статически (например Binance — из config)."""
    return BROKER_RATE_BY_EXCHANGE.get(exchange)

VIP_BONUS_BY_TIER: dict[str, Decimal] = {
    "bronze":   Decimal("0.00"),
    "silver":   Decimal("0.01"),
    "gold":     Decimal("0.02"),
    "platinum": Decimal("0.03"),
    "diamond":  Decimal("0.04"),
    "vip":      Decimal("0.05"),
}

VIP_THRESHOLDS: list[tuple[str, Decimal]] = [
    ("vip",      Decimal("20000")),
    ("diamond",  Decimal("5000")),
    ("platinum", Decimal("1000")),
    ("gold",     Decimal("250")),
    ("silver",   Decimal("50")),
    ("bronze",   Decimal("0")),
]


def tier_for_paid_out(paid_out_usd: Decimal) -> str:
    """Map cumulative paid-out USD to VIP tier (spec §3.2.3)."""
    for name, threshold in VIP_THRESHOLDS:
        if paid_out_usd >= threshold:
            return name
    return "bronze"


def _bonus(tier: str) -> Decimal:
    return VIP_BONUS_BY_TIER.get(tier, Decimal("0"))


@dataclass(frozen=True)
class CashbackSplit:
    broker_received: Decimal
    user_cb: Decimal
    referral_cb: Decimal
    platform_net: Decimal
    rate_applied: Decimal  # user_base_rate + vip_bonus


def compute_split(
    broker_received: Decimal,
    vip_tier: str,
    has_referrer: bool,
    *,
    user_base_rate: Decimal = USER_BASE_RATE,
    broker_rate: Decimal = BROKER_RATE,
) -> CashbackSplit:
    """Pure economic split of the broker commission we received.

    The exchange pays us ``broker_received`` (our share of the user's fee). From
    it we pay the user ``user_base_rate + VIP bonus`` of their full fee, the
    referrer 15% of the user's cashback, and keep the remainder. ``user_base_rate``
    / ``broker_rate`` are per-exchange (defaults = BingX). All values are Decimal.
    """
    rate = user_base_rate + _bonus(vip_tier)
    if broker_received <= 0:
        zero = Decimal("0")
        return CashbackSplit(zero, zero, zero, zero, rate)

    fee_paid_total = broker_received / broker_rate
    user_cb = fee_paid_total * rate
    ref_cb = user_cb * REFERRAL_RATE if has_referrer else Decimal("0")
    # Loss-leader: if our rebate is smaller than what we pay the user
    # (broker_rate < user-rate), platform_net goes negative — the platform eats
    # the difference. Value is still conserved: user + ref + platform == broker.
    platform_net = broker_received - user_cb - ref_cb
    return CashbackSplit(
        broker_received=broker_received,
        user_cb=user_cb,
        referral_cb=ref_cb,
        platform_net=platform_net,
        rate_applied=rate,
    )
