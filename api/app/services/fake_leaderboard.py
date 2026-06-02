"""Псевдослучайный лидерборд для «социального доказательства» на витрине.

Сид собирается из (seed_base, current_hour_utc) — поэтому выдача стабильна
в течение часа и сама обновляется каждый час, без cron-job'ов.

Ключевая идея: **один пул юзеров** на оба периода. Сортировка по
total earned даёт топ «Всё время», сортировка по recent earned — топ
«30 дней». Таким образом юзер из топа за 30 дней всегда присутствует и
в общем рейтинге (просто с большей суммой), а VIP-тиры стабильны между
переключениями. Это естественно для реального лидерборда.

Аналог `fake_withdrawals.py`, но для рейтинга.
"""
from __future__ import annotations

import hashlib
import random
import string
from datetime import datetime, timezone

# Имена — смесь русских/латинских/прочих. Цель — ощущение международной
# живой аудитории, без слишком явных стереотипов.
_FIRST_NAMES = [
    "Артём", "Иван", "Алексей", "Дмитрий", "Сергей", "Михаил", "Андрей",
    "Никита", "Максим", "Павел", "Александр", "Олег", "Денис", "Илья",
    "Кирилл", "Антон", "Тимур", "Виктор", "Роман", "Егор", "Владислав",
    "Marcus", "Alex", "John", "Mike", "David", "Chris", "James", "Daniel",
    "Ryan", "Tom", "Lukas", "Adam", "Anna", "Maria", "Elena", "Olga",
    "Yuki", "Hiro", "Kenji", "Wei", "Li", "Chen", "Aman", "Raj",
]
_LAST_INITIALS = list("КМСПВРТДБЗШГНОХЛФЦЧЕЯЮАИЭ")

# Префиксы для @username***
_USERNAME_PREFIXES = [
    "cry", "btc", "eth", "dex", "sol", "web", "dao", "alp", "the", "ape",
    "mid", "pro", "top", "vip", "fox", "lim", "mar", "lon", "neo", "max",
    "kop", "trd", "hod", "wal", "gem", "lev", "pip", "qnt", "ham", "lab",
    "ser", "ben", "ron", "kim", "nik", "sat", "vit", "art", "fin", "dev",
]

# Пул генерируется **ровно под limit** запроса — оба периода ('all' и '30d')
# показывают один и тот же набор юзеров, отличается только порядок и суммы.
# Это гарантирует: любой человек из топа за 30 дней присутствует и в общем
# рейтинге (просто с другой позицией и большей суммой), как в живом
# лидерборде. Если делать пул шире, чем limit, юзер из 30д-топа может
# оказаться за пределами видимых 50 общих — что и было багом.


def _seed_for(base: str) -> int:
    """Сид зависит только от base и часа — period НЕ влияет на пул,
    он влияет только на сортировку."""
    hour_key = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    h = hashlib.sha256(f"{base}:{hour_key}".encode()).hexdigest()
    return int(h[:12], 16)


def _name(rng: random.Random) -> str:
    style = rng.choices(
        ["first_only", "first_last", "username", "anon"],
        weights=[35, 35, 25, 5],
    )[0]
    if style == "first_only":
        return rng.choice(_FIRST_NAMES)
    if style == "first_last":
        return f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_INITIALS)}."
    if style == "username":
        suffix = "".join(rng.choices(string.ascii_lowercase, k=1))
        return f"@{rng.choice(_USERNAME_PREFIXES)}{suffix}***"
    return "Аноним"


def _tier_for_rank(rank: int) -> str:
    """Распределение VIP-тиров по позиции в общем рейтинге."""
    if rank <= 5:
        return "vip"
    if rank <= 12:
        return "diamond"
    if rank <= 22:
        return "platinum"
    if rank <= 32:
        return "gold"
    if rank <= 42:
        return "silver"
    return "bronze"


def _build_pool(rng: random.Random, size: int) -> list[dict]:
    """Сгенерировать пул юзеров с (name, earned_all, earned_30d, vip_tier).

    earned_all — общий заработок за всё время.
    earned_30d — заработок за последние 30 дней, всегда <= earned_all.
    vip_tier — закреплён за общим рангом, стабилен между переключениями
    period в UI.
    """
    used: set[str] = set()
    pool: list[dict] = []

    for i in range(size):
        # Уникальное имя в пределах пула.
        name = _name(rng)
        attempt = 0
        while name in used and attempt < 8:
            name = _name(rng)
            attempt += 1
        used.add(name)

        # earned_all: экспоненциально убывающее значение с шумом, чтобы
        # позиции в пуле перемешивались — после сортировки получается
        # естественная лесенка.
        top_amount = rng.uniform(8000, 15000)
        decay = 0.92 ** i
        noise = rng.uniform(0.7, 1.3)
        earned_all = max(20.0, round(top_amount * decay * noise, 2))

        # earned_30d — фракция от earned_all. У большинства небольшая
        # (стабильные пользователи, основной заработок в прошлом).
        # У ~20% — «активных» — большая фракция: они либо недавно пришли,
        # либо разогнались. Это даёт ротацию топа при переключении периода.
        is_hot = rng.random() < 0.2
        ratio = rng.uniform(0.55, 0.92) if is_hot else rng.uniform(0.05, 0.35)
        # Пол $3 — иначе у хвоста (earned_all=$20 + ratio=0.05) выходит $1
        # и список выглядит дёшево.
        earned_30d = max(3.0, round(earned_all * ratio, 2))

        pool.append(
            {
                "name": name,
                "earned_all": earned_all,
                "earned_30d": earned_30d,
            }
        )

    # VIP-тиры — по общему рангу. Один раз и навсегда, при любом period.
    pool.sort(key=lambda r: r["earned_all"], reverse=True)
    for i, p in enumerate(pool):
        p["vip_tier"] = _tier_for_rank(i + 1)
    return pool


def generate(seed_base: str, period: str = "all", limit: int = 50) -> list[dict]:
    """Return up to `limit` leaderboard rows for given period.

    Пул общий для обоих периодов — меняется только метрика сортировки.
    Это гарантирует пересечение топов: лидеры за 30д видны и во «Всё время».
    """
    rng = random.Random(_seed_for(seed_base))
    pool = _build_pool(rng, size=limit)

    key = "earned_30d" if period == "30d" else "earned_all"
    pool.sort(key=lambda r: r[key], reverse=True)

    return [
        {
            "rank": i + 1,
            "name": p["name"],
            "vip_tier": p["vip_tier"],
            "earned_usd": f"{p[key]:.2f}",
        }
        for i, p in enumerate(pool[:limit])
    ]
