"""Cashback Telegram bot — long polling + Redis pub/sub notifications."""
from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app import notifications
from app.handlers import start

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("bot")


async def main() -> None:
    token = os.environ.get("TG_BOT_TOKEN")
    if not token:
        # No token configured (e.g. demo / frontend-only deploy): idle instead of
        # crash-looping. Set TG_BOT_TOKEN in .env to enable the Telegram bot.
        log.warning("TG_BOT_TOKEN not set — bot idle. Set it in .env to enable the bot.")
        await asyncio.Event().wait()
        return

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(start.router)

    me = await bot.get_me()
    log.info("Bot started as @%s (id=%s)", me.username, me.id)

    await bot.delete_webhook(drop_pending_updates=False)

    polling_task = asyncio.create_task(
        dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    )
    notify_task = asyncio.create_task(notifications.listen(bot))

    done, pending = await asyncio.wait(
        {polling_task, notify_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for t in pending:
        t.cancel()
    for t in done:
        exc = t.exception()
        if exc:
            log.error("task crashed: %r", exc)


if __name__ == "__main__":
    asyncio.run(main())
