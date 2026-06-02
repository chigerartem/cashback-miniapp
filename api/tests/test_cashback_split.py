"""Pure-function tests for the cashback split (user / referral / platform)."""
from decimal import Decimal

import pytest

from app.services.cashback_math import (
    REFERRAL_RATE,
    USER_BASE_RATE,
    VIP_BONUS_BY_TIER,
    compute_split,
    tier_for_paid_out,
    user_base_rate_for,
)

D = Decimal


# ── reference table (broker $50, BingX rates) ─────────────────────────────

@pytest.mark.parametrize(
    "tier, has_ref, exp_user, exp_ref, exp_platform",
    [
        # Bronze, no referrer: broker $50 → user $30 / ref $0 / platform $20
        ("bronze", False, D("30.00"), D("0.00"), D("20.00")),
        # VIP +5%, no referrer: $50 → $35 / $0 / $15
        ("vip",    False, D("35.00"), D("0.00"), D("15.00")),
        # Bronze, with referrer: $50 → $30 / $4.50 / $15.50
        ("bronze", True,  D("30.00"), D("4.50"), D("15.50")),
        # VIP +5%, with referrer: $50 → $35 / $5.25 / $9.75
        ("vip",    True,  D("35.00"), D("5.25"), D("9.75")),
    ],
)
def test_split_matches_reference(tier, has_ref, exp_user, exp_ref, exp_platform):
    s = compute_split(broker_received=D("50"), vip_tier=tier, has_referrer=has_ref)
    assert s.user_cb == exp_user
    assert s.referral_cb == exp_ref
    assert s.platform_net == exp_platform


# ── tier ladder bonuses ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "tier, bonus",
    [
        ("bronze",   D("0.00")),
        ("silver",   D("0.01")),
        ("gold",     D("0.02")),
        ("platinum", D("0.03")),
        ("diamond",  D("0.04")),
        ("vip",      D("0.05")),
    ],
)
def test_tier_bonus_table(tier, bonus):
    assert VIP_BONUS_BY_TIER[tier] == bonus
    # rate_applied on a zero-broker split = base + bonus
    s = compute_split(D("0"), tier, False)
    assert s.rate_applied == USER_BASE_RATE + bonus


# ── tier_for_paid_out boundaries ─────────────────────────────────────────

@pytest.mark.parametrize(
    "paid_out, expected_tier",
    [
        (D("0"), "bronze"),
        (D("49.99"), "bronze"),
        (D("50"), "silver"),
        (D("249.99"), "silver"),
        (D("250"), "gold"),
        (D("999.99"), "gold"),
        (D("1000"), "platinum"),
        (D("4999.99"), "platinum"),
        (D("5000"), "diamond"),
        (D("19999"), "diamond"),
        (D("20000"), "vip"),
        (D("9999999"), "vip"),
    ],
)
def test_tier_thresholds(paid_out, expected_tier):
    assert tier_for_paid_out(paid_out) == expected_tier


# ── edge cases ────────────────────────────────────────────────────────────

def test_zero_broker_returns_zeros():
    s = compute_split(D("0"), "vip", True)
    assert s.user_cb == D("0")
    assert s.referral_cb == D("0")
    assert s.platform_net == D("0")


def test_referral_is_15pct_of_self_not_broker():
    """Referral cashback is 15% of the user's own cashback, not of the broker fee."""
    s = compute_split(D("50"), "bronze", True)
    assert s.user_cb == D("30")
    assert s.referral_cb == D("30") * REFERRAL_RATE
    assert s.referral_cb == D("4.5")


def test_loss_leader_platform_eats_negative_margin():
    """If our rebate is smaller than the user payout (broker_rate < user-rate),
    platform_net goes negative; value is still conserved."""
    s = compute_split(
        broker_received=D("10"),
        vip_tier="bronze",
        has_referrer=False,
        user_base_rate=D("0.10"),
        broker_rate=D("0.08"),  # 8% < 10% to the user → negative margin
    )
    assert s.user_cb == D("12.5")        # fee = 10 / 0.08 = 125; 125 * 0.10
    assert s.platform_net == D("-2.5")   # platform eats it (10 - 12.5)
    assert s.user_cb + s.referral_cb + s.platform_net == s.broker_received


def test_conservation_of_value():
    """user + referral + platform == broker_received (exact Decimal math)."""
    for tier in VIP_BONUS_BY_TIER:
        for has_ref in (False, True):
            s = compute_split(D("100"), tier, has_ref)
            total = s.user_cb + s.referral_cb + s.platform_net
            assert total == s.broker_received, f"tier={tier} ref={has_ref}: {total}"


def test_mexc_rate_registered_and_conserves():
    """MEXC is registered in the rate map (user_base 30%); the split conserves value."""
    assert user_base_rate_for("mexc") == D("0.30")
    s = compute_split(
        broker_received=D("20"),
        vip_tier="bronze",
        has_referrer=True,
        user_base_rate=user_base_rate_for("mexc"),
        broker_rate=D("0.50"),
    )
    assert s.user_cb == D("20") / D("0.50") * D("0.30")
    assert s.user_cb + s.referral_cb + s.platform_net == s.broker_received
