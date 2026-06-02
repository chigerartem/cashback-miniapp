"""Псевдослучайные выплаты для «социального доказательства» на витрине.

Сид собирается из (seed_base, current_hour_utc) — поэтому выдача стабильна
в течение часа и сама меняется каждый час, без cron-job'ов.
"""
from __future__ import annotations

import hashlib
import random
import string
from datetime import datetime, timedelta, timezone


def _seed_for(base: str) -> int:
    hour_key = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    h = hashlib.sha256(f"{base}:{hour_key}".encode()).hexdigest()
    return int(h[:12], 16)


def _mask_trc20(rng: random.Random) -> str:
    tail = "".join(rng.choices(string.ascii_lowercase + string.digits, k=2))
    return f"T***{tail}"


def _mask_uid(rng: random.Random) -> str:
    digits = "".join(rng.choices(string.digits, k=8))
    return f"{digits[:2]}***{digits[-2:]}"


def generate(seed_base: str, limit: int = 10) -> list[dict]:
    """Return up to `limit` plausible recent withdrawals ordered DESC by date."""
    rng = random.Random(_seed_for(seed_base))
    count = rng.randint(6, max(6, limit))
    now = datetime.now(timezone.utc)
    out: list[dict] = []
    for i in range(count):
        # Распределение сумм: чаще мелкие, реже крупные.
        bucket = rng.choices(["small", "mid", "large"], weights=[60, 30, 10])[0]
        if bucket == "small":
            amount = rng.uniform(20, 100)
        elif bucket == "mid":
            amount = rng.uniform(100, 350)
        else:
            amount = rng.uniform(350, 1200)
        amount = round(amount, 2)

        dest_type = rng.choices(["trc20", "bingx_uid"], weights=[85, 15])[0]
        masked = _mask_trc20(rng) if dest_type == "trc20" else _mask_uid(rng)

        # Время: первый ~часы назад, потом всё дальше в прошлое (до 7 дней).
        hours_back = rng.uniform(1 + i * 4, 6 + i * 16)
        completed_at = now - timedelta(hours=min(hours_back, 24 * 7))

        out.append(
            {
                "id": f"fake-{_seed_for(seed_base)}-{i}",
                "amount_usd": f"{amount:.2f}",
                "destination_type": dest_type,
                "destination_masked": masked,
                "completed_at": completed_at.isoformat(),
            }
        )
    out.sort(key=lambda x: x["completed_at"], reverse=True)
    return out[:limit]
