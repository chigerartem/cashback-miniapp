"""/start handler — welcome + Open App. Saves referral code to Redis on /start ref_XXX."""
from __future__ import annotations

import logging
import os
import re

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from redis.asyncio import Redis

log = logging.getLogger("bot.start")
router = Router()

WEB_DOMAIN = os.environ.get("WEB_DOMAIN", "cashback.example.com")
WEB_APP_URL = f"https://{WEB_DOMAIN}"
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
PENDING_REF_TTL_SECONDS = 86400  # 24h to claim
REF_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{4,32}$")

_redis: Redis | None = None


def _get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


WELCOME = (
    "Здравствуйте.\n\n"
    "Cashback возвращает часть комиссий с вашей торговли на криптобиржах.\n\n"
    "Нажмите <b>Open App</b>, чтобы подключить биржу и начать получать кешбэк."
)

WELCOME_WITH_REFERRER = (
    "Здравствуйте.\n\n"
    "Вас пригласил друг — после вашей первой сделки он получит 15% от вашего "
    "кешбэка, а вы — стандартную ставку + VIP-бонус.\n\n"
    "Нажмите <b>Open App</b>, чтобы продолжить."
)


def open_app_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Open App", web_app=WebAppInfo(url=WEB_APP_URL))],
        ]
    )


def _extract_ref_code(payload: str | None) -> str | None:
    """'ref_AbCdE' или 'AbCdE' → 'AbCdE'. Невалидное → None."""
    if not payload:
        return None
    payload = payload.strip()
    if payload.startswith("ref_"):
        payload = payload[4:]
    return payload if REF_CODE_PATTERN.match(payload) else None


@router.message(CommandStart(deep_link=True))
async def on_start_with_payload(message: Message) -> None:
    text = (message.text or "").removeprefix("/start").strip()
    code = _extract_ref_code(text)
    if code and message.from_user:
        try:
            await _get_redis().setex(
                f"pending_ref:{message.from_user.id}",
                PENDING_REF_TTL_SECONDS,
                code,
            )
            log.info("pending_ref saved tg_id=%s code=%s", message.from_user.id, code)
            await message.answer(WELCOME_WITH_REFERRER, reply_markup=open_app_keyboard())
            return
        except Exception:
            log.exception("failed to save pending_ref")
    await message.answer(WELCOME, reply_markup=open_app_keyboard())


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    await message.answer(WELCOME, reply_markup=open_app_keyboard())
