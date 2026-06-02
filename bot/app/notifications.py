"""Listen Redis pub/sub channel cashback:notify and DM users."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from redis.asyncio import Redis

log = logging.getLogger("bot.notify")

CHANNEL = "cashback:notify"
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")


def _short_tx(tx_hash: str | None) -> str:
    if not tx_hash:
        return ""
    if len(tx_hash) <= 14:
        return tx_hash
    return f"{tx_hash[:8]}…{tx_hash[-6:]}"


def _format_amount(s: str | None) -> str:
    try:
        return f"${float(s or 0):,.2f}"
    except (TypeError, ValueError):
        return f"${s}"


def _render(event_type: str, payload: dict[str, Any]) -> str | None:
    if event_type == "withdrawal.completed":
        amount = _format_amount(payload.get("amount_usd"))
        dest = "BingX UID" if payload.get("destination_type") == "bingx_uid" else "TRC-20"
        tx = payload.get("tx_hash")
        tail = f"\n\nTX: <code>{_short_tx(tx)}</code>" if tx else ""
        return (
            f"<b>Выплата выполнена</b>\n\n"
            f"Сумма: <b>{amount}</b>\nКуда: {dest}{tail}"
        )

    if event_type == "withdrawal.failed":
        amount = _format_amount(payload.get("amount_usd"))
        reason = payload.get("reason") or "не указана"
        return (
            f"<b>Заявка на вывод отклонена</b>\n\n"
            f"Сумма: <b>{amount}</b>\nПричина: {reason}\n\n"
            f"Средства возвращены на баланс."
        )

    if event_type == "referral.new":
        name = payload.get("invitee_name") or "Новый участник"
        username = payload.get("invitee_username")
        handle = f" @{username}" if username else ""
        return (
            f"<b>Новый реферал</b>\n\n"
            f"{name}{handle} зарегистрировался по вашей ссылке.\n"
            f"С каждой его сделки вы будете получать 15% его кешбэка."
        )

    if event_type == "tier.upgraded":
        new_tier = (payload.get("new_tier") or "").capitalize() or "новый уровень"
        rate = payload.get("rate_pct")
        rate_txt = f" Ставка кешбэка: <b>{rate}%</b>." if rate else ""
        return (
            f"<b>Поздравляем — новый VIP-тир</b>\n\n"
            f"Вы достигли уровня <b>{new_tier}</b>.{rate_txt}"
        )

    return None


async def _handle(bot: Bot, raw: str) -> None:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("ignored non-json message: %r", raw[:200])
        return

    tg_id = msg.get("tg_id")
    event_type = msg.get("type")
    payload = msg.get("payload") or {}
    if not (isinstance(tg_id, int) and event_type):
        log.warning("ignored malformed message: %s", msg)
        return

    text = _render(event_type, payload)
    if text is None:
        log.info("no renderer for event=%s — skipped", event_type)
        return

    try:
        await bot.send_message(tg_id, text)
        log.info("sent %s to tg_id=%s", event_type, tg_id)
    except TelegramForbiddenError:
        log.info("tg_id=%s blocked the bot — skipped", tg_id)
    except TelegramBadRequest as exc:
        log.warning("send to tg_id=%s failed: %s", tg_id, exc)
    except Exception:
        log.exception("send to tg_id=%s crashed", tg_id)


async def listen(bot: Bot) -> None:
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe(CHANNEL)
    log.info("subscribed to %s", CHANNEL)
    try:
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            data = msg.get("data")
            if isinstance(data, str):
                await _handle(bot, data)
    finally:
        await pubsub.close()
        await redis.aclose()
