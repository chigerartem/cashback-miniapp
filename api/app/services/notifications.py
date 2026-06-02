"""Publish events to Redis pub/sub so the bot can DM users.

Channel: cashback:notify
Message: JSON {type, tg_id, payload}

Event types:
  withdrawal.completed  payload: {amount_usd, destination_type, tx_hash?}
  withdrawal.failed     payload: {amount_usd, reason}
  referral.new          payload: {referrer_tg_id, invitee_name, invitee_username?}
                        (tg_id in envelope = referrer to notify)
  tier.upgraded         payload: {old_tier, new_tier, rate_pct}
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.redis_client import redis as redis_client

log = logging.getLogger("notify")

CHANNEL = "cashback:notify"


async def notify_event(event_type: str, tg_id: int, payload: dict[str, Any]) -> None:
    """Best-effort publish. Logs but never raises — нотификации не должны ломать бизнес-логику."""
    msg = json.dumps({"type": event_type, "tg_id": int(tg_id), "payload": payload})
    try:
        n = await redis_client.publish(CHANNEL, msg)
        log.info("notify type=%s tg_id=%s subscribers=%s", event_type, tg_id, n)
    except Exception:
        log.exception("notify failed type=%s tg_id=%s", event_type, tg_id)
