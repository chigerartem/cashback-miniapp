"""Telegram Mini App initData validation.

See https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException, status

from app.config import settings

MAX_AGE_SECONDS = 86400  # 24h


def _parse_init_data(init_data: str) -> dict[str, str]:
    return dict(parse_qsl(init_data, keep_blank_values=True))


def _expected_hash(parsed: dict[str, str], bot_token: str) -> str:
    data_check_arr = [f"{k}={v}" for k, v in sorted(parsed.items()) if k != "hash"]
    data_check_string = "\n".join(data_check_arr)
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


def validate_init_data(init_data: str) -> dict:
    """Return parsed telegram user dict if init_data is valid; raise 401 otherwise.

    initData is signed by Telegram with the bot token (HMAC-SHA256); we verify
    against our single bot token. See the Telegram docs linked above.
    """
    if not settings.tg_bot_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "bot token not configured")

    parsed = _parse_init_data(init_data)
    given_hash = parsed.get("hash", "")
    if not given_hash:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing hash")

    if not hmac.compare_digest(_expected_hash(parsed, settings.tg_bot_token), given_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid hash")

    auth_date = int(parsed.get("auth_date", "0"))
    if not auth_date or time.time() - auth_date > MAX_AGE_SECONDS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "auth_date expired")

    user_json = parsed.get("user")
    if not user_json:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no user in init_data")
    return json.loads(user_json)


async def telegram_user(authorization: str | None = Header(None)) -> dict:
    """FastAPI dependency: returns parsed telegram user dict."""
    if not authorization or not authorization.startswith("tma "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing Authorization: tma <initData>")
    return validate_init_data(authorization[4:])
