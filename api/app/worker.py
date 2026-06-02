"""Background worker — APScheduler in asyncio.

Jobs:
  • daily_user_sync   — 05:05 UTC: вытягивает commission_data_list за вчера,
                        UPSERT в daily_user_commissions, потом cashback.accrue_for_date
  • daily_<exchange>_sync — Binance/Bitget/MEXC/BYDFi rebate pulls → accrue
  • invite_poll       — каждые 5 минут: для exchange_accounts.status='pending'
                        делает superior_check, при подтверждении → 'active'

Запуск: python -m app.worker (или python app/worker.py)
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import (
    DailyBinanceCommission,
    DailyBitgetCommission,
    DailyBydfiCommission,
    DailyMexcCommission,
    DailyUserCommission,
    ExchangeAccount,
)
from app.services.antifraud import run_fraud_check
from app.services.binance import BinanceAgentClient, BinanceError
from app.services.bingx import BingXAgentClient, BingXError
from app.services.bitget import BitgetAgentClient, BitgetError
from app.services.bydfi import BydfiAffiliateClient, BydfiError
from app.services.cashback import accrue_for_date
from app.services.mexc import MexcAffiliateClient, MexcError

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("worker")


def _dec(v) -> Decimal:
    return Decimal(str(v or "0"))


def _day_window_ms(d: date) -> tuple[int, int]:
    start_ms = int(datetime.combine(d, datetime.min.time(), timezone.utc).timestamp() * 1000)
    return start_ms, start_ms + 86_400_000 - 1


def _bingx_client() -> BingXAgentClient:
    return BingXAgentClient(
        api_key=settings.bingx_api_key,
        api_secret=settings.bingx_api_secret,
        base_url=settings.bingx_base_url,
        recv_window_ms=settings.bingx_recv_window_ms,
    )


def _bingx_configured() -> bool:
    return bool(settings.bingx_api_key and settings.bingx_api_secret)


# USD-стейблы — income в них считаем 1:1. Прочие активы пока пропускаем
# (нужна конвертация по цене), логируя сумму, чтобы не начислить неверно.
_USD_STABLES = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI", "USD"}


def _binance_client() -> BinanceAgentClient:
    return BinanceAgentClient(
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
        base_url=settings.binance_base_url,
        fapi_url=settings.binance_fapi_url,
        recv_window_ms=settings.binance_recv_window_ms,
    )


def _binance_rebate_rate() -> Decimal:
    try:
        return Decimal(str(settings.binance_rebate_rate or "0"))
    except Exception:
        return Decimal("0")


def _binance_configured() -> bool:
    """Binance-начисление активно только при заданных ключах И ставке ребейта>0
    (без ставки нельзя восстановить fee юзера из нашего income)."""
    return bool(
        settings.binance_api_key
        and settings.binance_api_secret
        and _binance_rebate_rate() > 0
    )


def _bitget_client() -> BitgetAgentClient:
    return BitgetAgentClient(
        api_key=settings.bitget_api_key,
        api_secret=settings.bitget_api_secret,
        passphrase=settings.bitget_api_passphrase,
        base_url=settings.bitget_base_url,
    )


def _bitget_rebate_rate() -> Decimal:
    try:
        return Decimal(str(settings.bitget_rebate_rate or "0"))
    except Exception:
        return Decimal("0")


def _bitget_configured() -> bool:
    """Bitget-начисление активно только при ключах (key+secret+passphrase) И
    ставке ребейта>0 (без неё не восстановить fee из rebateAmount)."""
    return bool(
        settings.bitget_api_key
        and settings.bitget_api_secret
        and settings.bitget_api_passphrase
        and _bitget_rebate_rate() > 0
    )


def _mexc_client() -> MexcAffiliateClient:
    return MexcAffiliateClient(
        api_key=settings.mexc_api_key,
        api_secret=settings.mexc_api_secret,
        base_url=settings.mexc_base_url,
    )


def _mexc_rebate_rate() -> Decimal:
    try:
        return Decimal(str(settings.mexc_rebate_rate or "0"))
    except Exception:
        return Decimal("0")


def _mexc_configured() -> bool:
    """MEXC-начисление активно только при ключах (key+secret) И ставке ребейта>0
    (без неё не восстановить fee из нашего ребейта)."""
    return bool(
        settings.mexc_api_key
        and settings.mexc_api_secret
        and _mexc_rebate_rate() > 0
    )


def _bydfi_client() -> BydfiAffiliateClient:
    return BydfiAffiliateClient(
        api_key=settings.bydfi_api_key,
        api_secret=settings.bydfi_api_secret,
        base_url=settings.bydfi_base_url,
    )


def _bydfi_rebate_rate() -> Decimal:
    try:
        return Decimal(str(settings.bydfi_rebate_rate or "0"))
    except Exception:
        return Decimal("0")


def _bydfi_configured() -> bool:
    """BYDFi-начисление активно только при ключах (key+secret) И ставке ребейта>0
    (без неё не восстановить fee из нашего ребейта)."""
    return bool(
        settings.bydfi_api_key
        and settings.bydfi_api_secret
        and _bydfi_rebate_rate() > 0
    )


# ── daily user sync ───────────────────────────────────────────────────────

async def _fetch_all_user_commissions(target_date: date) -> list[dict]:
    """Pull commission_data_list for all users, paginated. No `uid` filter."""
    page = 1
    page_size = 100
    out: list[dict] = []
    start_ms, end_ms = _day_window_ms(target_date)
    async with _bingx_client() as bx:
        while True:
            data = await bx.commission_data_list(
                start_ms=start_ms,
                end_ms=end_ms,
                page_index=page,
                page_size=page_size,
            )
            rows = (data or {}).get("list", []) or []
            out.extend(rows)
            total = int((data or {}).get("total") or 0)
            if page * page_size >= total or not rows:
                break
            page += 1
    return out


async def _upsert_user_commissions(
    session: AsyncSession, target_date: date, rows: list[dict]
) -> tuple[int, int]:
    """Map bingx uid → our user.id via exchange_accounts. UPSERT into daily_user_commissions."""
    if not rows:
        return 0, 0

    accounts_q = await session.execute(
        select(ExchangeAccount.exchange_uid, ExchangeAccount.user_id).where(
            ExchangeAccount.exchange == "bingx",
            ExchangeAccount.status == "active",
        )
    )
    bx_uid_to_user: dict[str, str] = {a.exchange_uid: a.user_id for a in accounts_q.all()}

    matched = 0
    unmatched = 0
    for row in rows:
        bx_uid = str(row.get("uid"))
        user_id = bx_uid_to_user.get(bx_uid)
        if not user_id:
            unmatched += 1
            continue
        matched += 1

        spot_v = _dec(row.get("spotTradingVolume"))
        swap_v = _dec(row.get("swapTradingVolume"))
        std_v = _dec(row.get("stdTradingVolume"))
        copy_v = _dec(row.get("extCopyTradingVolume"))
        mt5_v = _dec(row.get("mt5TradingVolume"))
        total_v = _dec(row.get("tradingVolume"))

        spot_c = _dec(row.get("spotCommissionVolume"))
        swap_c = _dec(row.get("swapCommissionVolume"))
        std_c = _dec(row.get("stdCommissionVolume"))
        copy_c = _dec(row.get("extCopyCommissionVolume"))
        mt5_c = _dec(row.get("mt5CommissionVolume"))
        total_c = _dec(row.get("commissionVolume"))

        values = dict(
            user_id=user_id,
            date=target_date,
            spot_volume_usd=spot_v,
            swap_volume_usd=swap_v,
            std_volume_usd=std_v,
            copy_volume_usd=copy_v,
            mt5_volume_usd=mt5_v,
            total_volume_usd=total_v,
            spot_commission_usd=spot_c,
            swap_commission_usd=swap_c,
            std_commission_usd=std_c,
            copy_commission_usd=copy_c,
            mt5_commission_usd=mt5_c,
            total_commission_usd=total_c,
            synced_at=datetime.now(timezone.utc),
        )
        stmt = pg_insert(DailyUserCommission).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "date"],
            set_={k: v for k, v in values.items() if k not in ("user_id", "date")},
        )
        await session.execute(stmt)

    await session.commit()
    return matched, unmatched


async def daily_user_sync(target_date: date | None = None) -> dict:
    """Pull yesterday's commissions, UPSERT, then accrue cashback."""
    if not _bingx_configured():
        log.warning("daily_user_sync skipped — BingX API key not configured")
        return {"status": "skipped", "reason": "no_bingx_credentials"}

    target_date = target_date or (datetime.now(timezone.utc).date() - timedelta(days=1))
    log.info("daily_user_sync start date=%s", target_date)

    try:
        rows = await _fetch_all_user_commissions(target_date)
    except BingXError as exc:
        log.error("daily_user_sync bingx fail: %s", exc)
        return {"status": "error", "reason": str(exc)}

    async with SessionLocal() as session:
        matched, unmatched = await _upsert_user_commissions(session, target_date, rows)
        summary = await accrue_for_date(session, target_date)

    result = {
        "status": "ok",
        "date": target_date.isoformat(),
        "rows_from_bingx": len(rows),
        "matched_to_users": matched,
        "unmatched_uids": unmatched,
        "accrual": summary,
    }
    log.info("daily_user_sync done: %s", result)
    return result


# ── daily binance sync ────────────────────────────────────────────────────

async def daily_binance_sync(target_date: date | None = None) -> dict:
    """Тянет ребейты Binance (apiReferral) за день, матчит по email → user,
    UPSERT в daily_binance_commissions, потом accrue_for_date(exchange='binance').

    income в rebate-записи — наша комиссия (в `asset`). Юзера опознаём по email
    (UID в данных Binance нет). USD-стейблы считаем 1:1; прочие активы пока
    пропускаем с предупреждением (нужна конвертация по цене).
    """
    if not _binance_configured():
        log.warning("daily_binance_sync skipped — binance not configured (key/secret/rebate_rate)")
        return {"status": "skipped", "reason": "binance_not_configured"}

    target_date = target_date or (datetime.now(timezone.utc).date() - timedelta(days=1))
    start_ms, end_ms = _day_window_ms(target_date)
    log.info("daily_binance_sync start date=%s", target_date)

    # email → user_id (только активные binance-аккаунты)
    async with SessionLocal() as session:
        accounts_q = await session.execute(
            select(ExchangeAccount.exchange_uid, ExchangeAccount.user_id).where(
                ExchangeAccount.exchange == "binance",
                ExchangeAccount.status == "active",
            )
        )
        email_to_user: dict[str, str] = {
            (e or "").strip().lower(): u for e, u in accounts_q.all()
        }

    if not email_to_user:
        return {"status": "ok", "rebate_rows": 0, "matched_users": 0, "note": "no binance accounts"}

    try:
        async with _binance_client() as bx:
            rows = await bx.spot_rebate_recent_record(limit=500, start_ms=start_ms, end_ms=end_ms)
    except BinanceError as exc:
        log.error("daily_binance_sync binance fail: %s", exc)
        return {"status": "error", "reason": str(exc)}

    if len(rows) >= 500:
        log.warning(
            "daily_binance_sync: получено %d записей (лимит 500) — возможна обрезка, "
            "нужна постраничная выборка по более узкому окну", len(rows),
        )

    per_user: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    skipped_assets: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    unmatched = 0
    for r in rows:
        email = str(r.get("email") or "").strip().lower()
        user_id = email_to_user.get(email)
        if not user_id:
            unmatched += 1
            continue
        income = _dec(r.get("income"))
        if income <= 0:
            continue
        asset = str(r.get("asset") or "").upper()
        if asset in _USD_STABLES:
            per_user[user_id] += income
        else:
            skipped_assets[asset] += income  # TODO: конвертация в USD по цене тикера

    if skipped_assets:
        log.warning(
            "daily_binance_sync: ребейты в не-USD активах пропущены (нужна конвертация): %s",
            {a: str(v) for a, v in skipped_assets.items()},
        )

    matched = 0
    async with SessionLocal() as session:
        for user_id, total in per_user.items():
            values = dict(
                user_id=user_id,
                date=target_date,
                total_volume_usd=Decimal("0"),
                total_commission_usd=total,
                synced_at=datetime.now(timezone.utc),
            )
            stmt = pg_insert(DailyBinanceCommission).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "date"],
                set_={k: v for k, v in values.items() if k not in ("user_id", "date")},
            )
            await session.execute(stmt)
            matched += 1
        await session.commit()

        summary = await accrue_for_date(
            session, target_date, exchange="binance", broker_rate=_binance_rebate_rate()
        )

    result = {
        "status": "ok",
        "date": target_date.isoformat(),
        "rebate_rows": len(rows),
        "matched_users": matched,
        "unmatched_emails": unmatched,
        "accrual": summary,
    }
    log.info("daily_binance_sync done: %s", result)
    return result


# ── daily bitget sync ──────────────────────────────────────────────────────

async def daily_bitget_sync(target_date: date | None = None) -> dict:
    """Тянет ребейты Bitget (agent customer-commissions) за день, матчит по UID
    → user, UPSERT в daily_bitget_commissions, потом accrue_for_date('bitget').

    rebateAmount — наш ребейт; реферал опознаётся по `uid` (в отличие от Binance
    по email). USD-стейблы считаем 1:1, прочие активы пропускаем. Имена полей
    (uid/rebateAmount/coin/id) — по докам Bitget v2; при расхождении уточнить
    probe'ом реальными ключами.
    """
    if not _bitget_configured():
        log.warning(
            "daily_bitget_sync skipped — bitget not configured (key/secret/passphrase/rebate_rate)"
        )
        return {"status": "skipped", "reason": "bitget_not_configured"}

    target_date = target_date or (datetime.now(timezone.utc).date() - timedelta(days=1))
    start_ms, end_ms = _day_window_ms(target_date)
    log.info("daily_bitget_sync start date=%s", target_date)

    # uid → user_id (только активные bitget-аккаунты)
    async with SessionLocal() as session:
        accounts_q = await session.execute(
            select(ExchangeAccount.exchange_uid, ExchangeAccount.user_id).where(
                ExchangeAccount.exchange == "bitget",
                ExchangeAccount.status == "active",
            )
        )
        uid_to_user: dict[str, str] = {
            str(ex_uid or "").strip(): user_id
            for ex_uid, user_id in accounts_q.all()
        }

    if not uid_to_user:
        return {"status": "ok", "rebate_rows": 0, "matched_users": 0, "note": "no bitget accounts"}

    # cursor-пагинация по endId (Bitget отдаёт его на уровне data), пока в
    # commissionList есть записи. Подтверждено probe'ом 2026-05-29.
    rows: list[dict] = []
    cursor: str | None = None
    try:
        async with _bitget_client() as bg:
            for _page in range(50):  # safety-cap от зацикливания
                page, cursor = await bg.agent_customer_commissions(
                    start_ms=start_ms, end_ms=end_ms, id_less_than=cursor, limit=100
                )
                if not page:
                    break
                rows.extend(page)
                if not cursor:
                    break
    except BitgetError as exc:
        log.error("daily_bitget_sync bitget fail: %s", exc)
        return {"status": "error", "reason": str(exc)}

    per_user: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    skipped_assets: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    unmatched = 0
    for r in rows:
        uid = str(r.get("uid") or "").strip()
        user_id = uid_to_user.get(uid)
        if not user_id:
            unmatched += 1
            continue
        income = _dec(r.get("rebateAmount"))
        if income <= 0:
            continue
        coin = str(r.get("coin") or r.get("currency") or "").upper()
        if coin in _USD_STABLES:
            per_user[user_id] += income
        else:
            skipped_assets[coin or "?"] += income  # TODO: конвертация в USD по цене

    if skipped_assets:
        log.warning(
            "daily_bitget_sync: ребейты в не-USD активах пропущены (нужна конвертация): %s",
            {a: str(v) for a, v in skipped_assets.items()},
        )

    matched = 0
    async with SessionLocal() as session:
        for user_id, total in per_user.items():
            values = dict(
                user_id=user_id,
                date=target_date,
                total_volume_usd=Decimal("0"),
                total_commission_usd=total,
                synced_at=datetime.now(timezone.utc),
            )
            stmt = pg_insert(DailyBitgetCommission).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "date"],
                set_={k: v for k, v in values.items() if k not in ("user_id", "date")},
            )
            await session.execute(stmt)
            matched += 1
        await session.commit()

        summary = await accrue_for_date(
            session, target_date, exchange="bitget", broker_rate=_bitget_rebate_rate()
        )

    result = {
        "status": "ok",
        "date": target_date.isoformat(),
        "rebate_rows": len(rows),
        "matched_users": matched,
        "unmatched_uids": unmatched,
        "accrual": summary,
    }
    log.info("daily_bitget_sync done: %s", result)
    return result


# ── daily mexc sync ─────────────────────────────────────────────────────────

def _mexc_extract_rows(data) -> tuple[list[dict], int | None]:
    """Из data-узла affiliate/commission достаёт (записи, totalPage).

    MEXC отдаёт либо {"resultList":[...], "totalPage":N, "currentPage":p}, либо
    {"list":[...]}, либо голый list. totalPage None → пагинируем пока непусто.
    """
    if isinstance(data, list):
        return data, None
    if isinstance(data, dict):
        rows = data.get("resultList") or data.get("list") or data.get("data") or []
        if not isinstance(rows, list):
            rows = []
        total_page = data.get("totalPage") or data.get("totalPageNum")
        try:
            total_page = int(total_page) if total_page is not None else None
        except (TypeError, ValueError):
            total_page = None
        return rows, total_page
    return [], None


async def daily_mexc_sync(target_date: date | None = None) -> dict:
    """Тянет ребейты MEXC (affiliate/commission) за день, матчит по UID → user,
    UPSERT в daily_mexc_commissions, потом accrue_for_date('mexc').

    Реферал опознаётся по числовому `uid` (как Bitget). Сумма нашего ребейта —
    поле `total`/`commission` (у MEXC в USDT). Envelope/пагинация подтверждены
    probe'ом 2026-06-01 (resultList/totalPage); имена полей ВНУТРИ записи — до
    первого реферала (resultList был пуст), заложены с fallback'ами ниже. USD-
    стейблы считаем 1:1, прочие пропускаем.
    """
    if not _mexc_configured():
        log.warning(
            "daily_mexc_sync skipped — mexc not configured (key/secret/rebate_rate)"
        )
        return {"status": "skipped", "reason": "mexc_not_configured"}

    target_date = target_date or (datetime.now(timezone.utc).date() - timedelta(days=1))
    start_ms, end_ms = _day_window_ms(target_date)
    log.info("daily_mexc_sync start date=%s", target_date)

    # uid → user_id (только активные mexc-аккаунты)
    async with SessionLocal() as session:
        accounts_q = await session.execute(
            select(ExchangeAccount.exchange_uid, ExchangeAccount.user_id).where(
                ExchangeAccount.exchange == "mexc",
                ExchangeAccount.status == "active",
            )
        )
        uid_to_user: dict[str, str] = {
            str(ex_uid or "").strip(): user_id
            for ex_uid, user_id in accounts_q.all()
        }

    if not uid_to_user:
        return {"status": "ok", "rebate_rows": 0, "matched_users": 0, "note": "no mexc accounts"}

    # page-пагинация: тянем, пока есть записи и не вышли за totalPage.
    rows: list[dict] = []
    try:
        async with _mexc_client() as mx:
            page = 1
            for _page in range(50):  # safety-cap от зацикливания
                data = await mx.affiliate_commission(
                    start_ms=start_ms, end_ms=end_ms, page=page, page_size=100
                )
                page_rows, total_page = _mexc_extract_rows(data)
                if not page_rows:
                    break
                rows.extend(page_rows)
                if total_page is not None and page >= total_page:
                    break
                page += 1
    except MexcError as exc:
        log.error("daily_mexc_sync mexc fail: %s", exc)
        return {"status": "error", "reason": str(exc)}

    per_user: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    skipped_assets: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    unmatched = 0
    for r in rows:
        uid = str(r.get("uid") or r.get("inviteeUid") or "").strip()
        user_id = uid_to_user.get(uid)
        if not user_id:
            unmatched += 1
            continue
        income = _dec(r.get("total") or r.get("commission") or r.get("totalCommission"))
        if income <= 0:
            continue
        # affiliate/commission обычно агрегирует в USDT; если появится asset≠USD —
        # пропускаем с предупреждением (как binance/bitget), нужна конвертация.
        asset = str(r.get("asset") or r.get("coin") or "USDT").upper()
        if asset in _USD_STABLES:
            per_user[user_id] += income
        else:
            skipped_assets[asset] += income

    if skipped_assets:
        log.warning(
            "daily_mexc_sync: ребейты в не-USD активах пропущены (нужна конвертация): %s",
            {a: str(v) for a, v in skipped_assets.items()},
        )

    matched = 0
    async with SessionLocal() as session:
        for user_id, total in per_user.items():
            values = dict(
                user_id=user_id,
                date=target_date,
                total_volume_usd=Decimal("0"),
                total_commission_usd=total,
                synced_at=datetime.now(timezone.utc),
            )
            stmt = pg_insert(DailyMexcCommission).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "date"],
                set_={k: v for k, v in values.items() if k not in ("user_id", "date")},
            )
            await session.execute(stmt)
            matched += 1
        await session.commit()

        summary = await accrue_for_date(
            session, target_date, exchange="mexc", broker_rate=_mexc_rebate_rate()
        )

    result = {
        "status": "ok",
        "date": target_date.isoformat(),
        "rebate_rows": len(rows),
        "matched_users": matched,
        "unmatched_uids": unmatched,
        "accrual": summary,
    }
    log.info("daily_mexc_sync done: %s", result)
    return result


# ── daily bydfi sync ──────────────────────────────────────────────────────

async def daily_bydfi_sync(target_date: date | None = None) -> dict:
    """Тянет ребейты BYDFi (agent/affiliate_commission) за день, матчит по UID → user,
    UPSERT в daily_bydfi_commissions, потом accrue_for_date('bydfi').

    Реферал опознаётся по числовому `uid`. Наш ребейт — поле `commission` (USDT).
    Окно affiliate_commission ≤180 дней (берём один день). USD-стейблы 1:1, прочие
    пропускаем. broker_rate (для восстановления fee) — единый bydfi_rebate_rate;
    при смешанной spot(0.5)/swap(0.6) торговле это приближение (см. config).
    """
    if not _bydfi_configured():
        log.warning(
            "daily_bydfi_sync skipped — bydfi not configured (key/secret/rebate_rate)"
        )
        return {"status": "skipped", "reason": "bydfi_not_configured"}

    target_date = target_date or (datetime.now(timezone.utc).date() - timedelta(days=1))
    start_ms, end_ms = _day_window_ms(target_date)
    log.info("daily_bydfi_sync start date=%s", target_date)

    # uid → user_id (только активные bydfi-аккаунты)
    async with SessionLocal() as session:
        accounts_q = await session.execute(
            select(ExchangeAccount.exchange_uid, ExchangeAccount.user_id).where(
                ExchangeAccount.exchange == "bydfi",
                ExchangeAccount.status == "active",
            )
        )
        uid_to_user: dict[str, str] = {
            str(ex_uid or "").strip(): user_id
            for ex_uid, user_id in accounts_q.all()
        }

    if not uid_to_user:
        return {"status": "ok", "rebate_rows": 0, "matched_users": 0, "note": "no bydfi accounts"}

    rows: list[dict] = []
    try:
        async with _bydfi_client() as bd:
            page = 1
            for _page in range(50):  # safety-cap от зацикливания
                page_rows = await bd.affiliate_commission(
                    start_ms=start_ms, end_ms=end_ms, page=page, rows=100
                )
                if not page_rows:
                    break
                rows.extend(page_rows)
                if len(page_rows) < 100:
                    break
                page += 1
    except BydfiError as exc:
        log.error("daily_bydfi_sync bydfi fail: %s", exc)
        return {"status": "error", "reason": str(exc)}

    per_user: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    skipped_assets: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    unmatched = 0
    for r in rows:
        uid = str(r.get("uid") or "").strip()
        user_id = uid_to_user.get(uid)
        if not user_id:
            unmatched += 1
            continue
        income = _dec(r.get("commission") or r.get("total"))
        if income <= 0:
            continue
        asset = str(r.get("coin") or "USDT").upper()
        if asset in _USD_STABLES:
            per_user[user_id] += income
        else:
            skipped_assets[asset] += income

    if skipped_assets:
        log.warning(
            "daily_bydfi_sync: ребейты в не-USD активах пропущены (нужна конвертация): %s",
            {a: str(v) for a, v in skipped_assets.items()},
        )

    matched = 0
    async with SessionLocal() as session:
        for user_id, total in per_user.items():
            values = dict(
                user_id=user_id,
                date=target_date,
                total_volume_usd=Decimal("0"),
                total_commission_usd=total,
                synced_at=datetime.now(timezone.utc),
            )
            stmt = pg_insert(DailyBydfiCommission).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "date"],
                set_={k: v for k, v in values.items() if k not in ("user_id", "date")},
            )
            await session.execute(stmt)
            matched += 1
        await session.commit()

        summary = await accrue_for_date(
            session, target_date, exchange="bydfi", broker_rate=_bydfi_rebate_rate()
        )

    result = {
        "status": "ok",
        "date": target_date.isoformat(),
        "rebate_rows": len(rows),
        "matched_users": matched,
        "unmatched_uids": unmatched,
        "accrual": summary,
    }
    log.info("daily_bydfi_sync done: %s", result)
    return result


# ── invite poll ────────────────────────────────────────────────────────────

async def invite_poll() -> dict:
    """Check pending bingx exchange_accounts via superior_check; promote to active."""
    if not _bingx_configured():
        return {"status": "skipped"}

    async with SessionLocal() as session:
        pending = (
            await session.execute(
                select(ExchangeAccount).where(
                    ExchangeAccount.exchange == "bingx",
                    ExchangeAccount.status == "pending",
                )
            )
        ).scalars().all()

        if not pending:
            return {"status": "ok", "checked": 0, "promoted": 0}

        promoted = 0
        async with _bingx_client() as bx:
            for account in pending:
                try:
                    relation = await bx.invite_relation_check(int(account.exchange_uid))
                except BingXError as exc:
                    log.warning("invite_poll uid=%s err=%s", account.exchange_uid, exc)
                    continue
                if relation and relation.get("inviteResult"):
                    account.status = "active"
                    account.invited_at = datetime.now(timezone.utc)
                    promoted += 1

        if promoted:
            await session.commit()

    log.info("invite_poll checked=%d promoted=%d", len(pending), promoted)
    return {"status": "ok", "checked": len(pending), "promoted": promoted}


# ── main ──────────────────────────────────────────────────────────────────

async def main() -> None:
    log.info(
        "worker starting (bingx=%s binance=%s bitget=%s mexc=%s bydfi=%s env=%s)",
        _bingx_configured(),
        _binance_configured(),
        _bitget_configured(),
        _mexc_configured(),
        _bydfi_configured(),
        settings.env,
    )
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        daily_user_sync,
        CronTrigger(hour=5, minute=5),
        id="daily_user_sync",
        misfire_grace_time=3600,
    )
    # Midday safety re-run — guards against a missed nightly cron and late edits
    # to the exchange aggregates. The accrual is idempotent: re-running the same
    # date yields the same result.
    scheduler.add_job(
        daily_user_sync,
        CronTrigger(hour=12, minute=5),
        id="daily_user_sync_midday",
        misfire_grace_time=3600,
    )
    # Binance apiReferral sync — после BingX (тот же паттерн, отдельный источник).
    scheduler.add_job(
        daily_binance_sync,
        CronTrigger(hour=5, minute=15),
        id="daily_binance_sync",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        daily_binance_sync,
        CronTrigger(hour=12, minute=15),
        id="daily_binance_sync_midday",
        misfire_grace_time=3600,
    )
    # Bitget agent sync — UID-based, тот же паттерн, отдельный источник.
    scheduler.add_job(
        daily_bitget_sync,
        CronTrigger(hour=5, minute=20),
        id="daily_bitget_sync",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        daily_bitget_sync,
        CronTrigger(hour=12, minute=20),
        id="daily_bitget_sync_midday",
        misfire_grace_time=3600,
    )
    # MEXC affiliate sync — UID-based, тот же паттерн, отдельный источник.
    scheduler.add_job(
        daily_mexc_sync,
        CronTrigger(hour=5, minute=25),
        id="daily_mexc_sync",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        daily_mexc_sync,
        CronTrigger(hour=12, minute=25),
        id="daily_mexc_sync_midday",
        misfire_grace_time=3600,
    )
    # BYDFi affiliate sync — UID-based, тот же паттерн, отдельный источник.
    scheduler.add_job(
        daily_bydfi_sync,
        CronTrigger(hour=5, minute=30),
        id="daily_bydfi_sync",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        daily_bydfi_sync,
        CronTrigger(hour=12, minute=30),
        id="daily_bydfi_sync_midday",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        invite_poll,
        IntervalTrigger(minutes=5),
        id="invite_poll",
        misfire_grace_time=60,
    )
    scheduler.add_job(
        run_fraud_check,
        CronTrigger(hour=5, minute=30),
        id="fraud_check",
        misfire_grace_time=3600,
    )
    scheduler.start()
    log.info("scheduler started, jobs: %s", [j.id for j in scheduler.get_jobs()])
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
