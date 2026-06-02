"""Exchange connection routes."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import telegram_user
from app.config import settings
from app.db import get_session
from app.models import ExchangeAccount, User
from app.services.binance import BinanceAgentClient, BinanceError
from app.services.bingx import BingXAgentClient, BingXError
from app.services.bitget import BitgetAgentClient, BitgetError
from app.services.bydfi import BydfiAffiliateClient, BydfiError
from app.services.cashback_math import user_base_rate_for
from app.services.mexc import MexcAffiliateClient, MexcError

router = APIRouter(prefix="/api/exchanges", tags=["exchanges"])

BINGX = "bingx"
BINANCE = "binance"
BITGET = "bitget"
MEXC = "mexc"
BYDFI = "bydfi"
# Binance apiReferral идентифицирует рефералов по email (UID в ребейт-данных нет),
# поэтому для Binance юзер вводит email своего аккаунта, а не числовой UID.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Каталог поддерживаемых бирж. available=False → показываем как «Скоро».
# Логотипы из CoinGecko (публичные exchange icons).
#
# Fees — стандартные ставки уровня 0 / без VIP / без BNB-style скидок.
# broker_rate — наша доля от комиссии биржи (то, что биржа отдаёт нам как
# affiliate/broker), это потолок, реальная цифра по контракту может быть
# ниже. Используется для расчёта максимально возможного кешбэка юзеру.
EXCHANGE_CATALOG = [
    {
        "slug": "bingx", "name": "BingX", "brand_color": "#1f6cf0", "domain": "bingx.com",
        "logo": "https://coin-images.coingecko.com/markets/images/812/large/YtFwQwJr_400x400.jpg",
        "available": True,
        "fees": {
            "spot_taker_pct": 0.10,
            "spot_maker_pct": 0.10,
            "perp_taker_pct": 0.05,
            "perp_maker_pct": 0.02,
        },
        "broker_rate_pct": 55,
        "volume_bonus": {"threshold_usd": 10_000_000, "reward_usd": 650},
    },
    {
        "slug": "binance", "name": "Binance", "brand_color": "#F0B90B", "domain": "binance.com",
        # Логотип из favicon binance.com (надёжно рендерится); list_exchanges всё равно
        # добавляет favicon-фолбэки. При желании заменить на крупный ассет.
        "logo": "https://www.google.com/s2/favicons?domain=binance.com&sz=128",
        "available": True,
        "fees": {
            "spot_taker_pct": 0.10,
            "spot_maker_pct": 0.10,
            "perp_taker_pct": 0.05,
            "perp_maker_pct": 0.02,
        },
        "broker_rate_pct": 40,
        "default_referral_url": settings.binance_default_referral_url,
    },
    {
        "slug": "bitget", "name": "Bitget", "brand_color": "#00E5FF", "domain": "bitget.com",
        # Bitget logo via favicon (like Binance); swap for a bundled asset if desired.
        "logo": "https://www.google.com/s2/favicons?domain=bitget.com&sz=128",
        "available": True,
        "fees": {
            "spot_taker_pct": 0.10,
            "spot_maker_pct": 0.10,
            "perp_taker_pct": 0.06,
            "perp_maker_pct": 0.02,
        },
        # Доля Bitget affiliate, которую биржа отдаёт нам. Реальной ставки пока
        # нет → 0 (как и BITGET_REBATE_RATE, accrual gated). Обновить по контракту.
        "broker_rate_pct": 0,
        "default_referral_url": settings.bitget_default_referral_url,
    },
    {
        "slug": "mexc", "name": "MEXC", "brand_color": "#0B61FF", "domain": "mexc.com",
        # Favicon mexc.com (как Bitget/Binance). Заменить на точный ассет, когда
        # положим файл в web/public/exchanges/.
        "logo": "https://www.google.com/s2/favicons?domain=mexc.com&sz=128",
        "available": True,
        # Стандартные публичные ставки MEXC (уровень 0, без VIP). Только для UI.
        "fees": {
            "spot_taker_pct": 0.05,
            "spot_maker_pct": 0.00,
            "perp_taker_pct": 0.02,
            "perp_maker_pct": 0.00,
        },
        # Доля MEXC affiliate, которую биржа отдаёт нам: 50% на spot и futures.
        "broker_rate_pct": 50,
        "default_referral_url": settings.mexc_default_referral_url,
    },
    {
        "slug": "bydfi", "name": "BYDFi", "brand_color": "#F5C518", "domain": "bydfi.com",
        "logo": "https://www.google.com/s2/favicons?domain=bydfi.com&sz=128",
        "available": True,
        # Публичные ставки уровня 0 (только UI; точные — уточнить у BYDFi).
        "fees": {
            "spot_taker_pct": 0.10,
            "spot_maker_pct": 0.10,
            "perp_taker_pct": 0.06,
            "perp_maker_pct": 0.02,
        },
        # Доля BYDFi affiliate, которую биржа отдаёт нам: spot 50% / swap 60%
        # (probe agent/teams 2026-06-01). В каталоге — потолок (swap 60).
        "broker_rate_pct": 60,
        "default_referral_url": settings.bydfi_default_referral_url,
    },
]

CATALOG_BY_SLUG = {e["slug"]: e for e in EXCHANGE_CATALOG}


class ConnectBody(BaseModel):
    # Для BingX — числовой UID; для Binance — email аккаунта. Конкретный формат
    # валидируется в connect_exchange по бирже (см. _connect_binance / BingX-ветку).
    uid: str = Field(min_length=3, max_length=128)


async def _current_user(
    session: AsyncSession, tg_user: dict
) -> User:
    tg_id = int(tg_user["id"])
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Пользователь не найден. Откройте приложение, чтобы создать профиль.",
        )
    return user


def _referral_url_for(slug: str) -> str | None:
    """Referral URL for an exchange — one platform link per exchange from settings."""
    if slug == BINGX:
        return settings.bingx_default_referral_url or None
    catalog = CATALOG_BY_SLUG.get(slug)
    return (catalog.get("default_referral_url") or None) if catalog else None


@router.get("")
async def list_exchanges(
    tg_user: dict = Depends(telegram_user),
    session: AsyncSession = Depends(get_session),
):
    user = await _current_user(session, tg_user)
    accounts = await session.execute(
        select(ExchangeAccount).where(ExchangeAccount.user_id == user.id)
    )
    by_exchange = {a.exchange: a for a in accounts.scalars()}

    result = []
    for catalog in EXCHANGE_CATALOG:
        slug = catalog["slug"]
        account = by_exchange.get(slug)
        if not catalog["available"]:
            status_value = "coming_soon"
        elif account:
            status_value = account.status
        else:
            status_value = "not_connected"
        domain = catalog["domain"]
        # Platform referral link for this exchange (from settings; may be empty).
        ref_url = _referral_url_for(slug)
        result.append(
            {
                "slug": slug,
                "name": catalog["name"],
                "brand_color": catalog["brand_color"],
                "domain": domain,
                "logo_urls": [
                    catalog["logo"],
                    f"https://icons.duckduckgo.com/ip3/{domain}.ico",
                    f"https://www.google.com/s2/favicons?domain={domain}&sz=128",
                ],
                "available": catalog["available"],
                "referral_url": ref_url,
                "status": status_value,
                "uid": account.exchange_uid if account else None,
                "fees": catalog["fees"],
                "broker_rate_pct": catalog["broker_rate_pct"],
                # Базовый % юзеру от его fee (без VIP-бонуса): bingx 30, binance 5.
                "user_base_rate_pct": float(user_base_rate_for(slug) * 100),
            }
        )
    # Порядок в Mini App: доступные биржи первыми, внутри — по убыванию % кешбэка
    # юзеру (user_base_rate_pct). Stable-сортировка: при равных ставках сохраняется
    # порядок EXCHANGE_CATALOG (bingx перед mexc при равных 30%).
    result.sort(key=lambda e: (e["available"], e["user_base_rate_pct"]), reverse=True)
    return result


async def _connect_binance(
    session: AsyncSession,
    user: User,
    body: ConnectBody,
) -> dict:
    """Привязка Binance по email с РЕАЛЬНЫМ verify (аналог BingX/MEXC/Bitget).

    Binance опознаёт рефералов по email/customerId (UID нет). Принимаем email,
    только если он есть в нашем customization-маппинге (см. is_referral_email —
    тянем весь список и матчим локально, серверный фильтр по email = 403). Иначе
    422. Email уникален на (exchange, exchange_uid) — один email нельзя привязать
    к двум юзерам. Повторное подключение уже-active того же email verify пропускает.
    """
    email = body.uid.strip().lower()
    if len(email) > 128 or not _EMAIL_RE.match(email):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Введите корректный email вашего аккаунта Binance",
        )

    existing = (
        await session.execute(
            select(ExchangeAccount).where(
                ExchangeAccount.user_id == user.id,
                ExchangeAccount.exchange == BINANCE,
            )
        )
    ).scalar_one_or_none()
    if existing and existing.status == "active" and existing.exchange_uid != email:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "К вашему аккаунту уже привязан другой Binance email",
        )
    if existing and existing.status == "active" and existing.exchange_uid == email:
        return {"status": "active", "uid": email}

    if not settings.binance_api_key or not settings.binance_api_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Интеграция с Binance временно недоступна",
        )

    try:
        async with BinanceAgentClient(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            base_url=settings.binance_base_url,
            fapi_url=settings.binance_fapi_url,
            recv_window_ms=settings.binance_recv_window_ms,
        ) as bn:
            is_ref = await bn.is_referral_email(email)
    except BinanceError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Binance не подтвердил привязку (код {exc.code})",
        ) from exc

    if not is_ref:
        if existing and existing.status != "active":
            await session.delete(existing)
            await session.commit()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Этот email не привязан к нашей реферальной программе Binance. "
            "Зарегистрируйтесь на Binance по нашей ссылке или проверьте, что email указан верно.",
        )

    if existing:
        existing.exchange_uid = email
        existing.status = "active"
        if existing.invited_at is None:
            existing.invited_at = datetime.now(timezone.utc)
        await session.commit()
        return {"status": "active", "uid": email}

    account = ExchangeAccount(
        user_id=user.id,
        exchange=BINANCE,
        exchange_uid=email,
        status="active",
        invited_at=datetime.now(timezone.utc),
    )
    session.add(account)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Этот Binance email уже привязан к другому пользователю",
        ) from exc
    return {"status": "active", "uid": email}


async def _connect_mexc(
    session: AsyncSession,
    user: User,
    body: ConnectBody,
) -> dict:
    """Привязка MEXC по числовому UID с РЕАЛЬНЫМ verify (аналог BingX).

    Принимаем UID, только если affiliate/referral подтверждает, что он привязан к
    нашему inviteCode (см. MexcAffiliateClient.is_referral). Иначе 422 — как «UID не
    наш реферал» у BingX. Это закрывает дыру, где stub-attach принимал любой UID.

    Verify-окно ≤30 дней (ограничение MEXC) — рассчитано на подключение свежих
    рефералов. Повторное подключение уже-active того же UID verify пропускает (он мог
    быть привязан раньше окна; повторная проверка ложно отклонила бы).
    """
    existing = (
        await session.execute(
            select(ExchangeAccount).where(
                ExchangeAccount.user_id == user.id,
                ExchangeAccount.exchange == MEXC,
            )
        )
    ).scalar_one_or_none()

    # active с другим UID менять нельзя (как у BingX).
    if existing and existing.status == "active" and existing.exchange_uid != body.uid:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "К вашему аккаунту уже привязан другой MEXC UID",
        )
    # Переподключение того же уже-active UID — verify не повторяем.
    if existing and existing.status == "active" and existing.exchange_uid == body.uid:
        return {"status": "active", "uid": existing.exchange_uid}

    if not settings.mexc_api_key or not settings.mexc_api_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Интеграция с MEXC временно недоступна",
        )

    now = datetime.now(timezone.utc)
    end_ms = int(now.timestamp() * 1000)
    start_ms = int((now - timedelta(days=30)).timestamp() * 1000)
    try:
        async with MexcAffiliateClient(
            api_key=settings.mexc_api_key,
            api_secret=settings.mexc_api_secret,
            base_url=settings.mexc_base_url,
        ) as mx:
            is_ref = await mx.is_referral(body.uid, start_ms=start_ms, end_ms=end_ms)
    except MexcError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"MEXC не подтвердил привязку (код {exc.code})",
        ) from exc

    if not is_ref:
        # Чистим мёртвую pending/failed-запись от прошлой попытки (как BingX).
        if existing and existing.status != "active":
            await session.delete(existing)
            await session.commit()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Этот UID не привязан к нашей реферальной программе MEXC. "
            "Зарегистрируйтесь на MEXC по нашей ссылке или проверьте, что UID указан верно.",
        )

    if existing:
        existing.exchange_uid = body.uid
        existing.status = "active"
        if existing.invited_at is None:
            existing.invited_at = datetime.now(timezone.utc)
        await session.commit()
        return {"status": "active", "uid": existing.exchange_uid}

    account = ExchangeAccount(
        user_id=user.id,
        exchange=MEXC,
        exchange_uid=body.uid,
        status="active",
        invited_at=datetime.now(timezone.utc),
    )
    session.add(account)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Этот MEXC UID уже привязан к другому пользователю",
        ) from exc
    return {"status": "active", "uid": account.exchange_uid}


async def _connect_bitget(
    session: AsyncSession,
    user: User,
    body: ConnectBody,
) -> dict:
    """Привязка Bitget по числовому UID с РЕАЛЬНЫМ verify (аналог BingX/MEXC).

    Принимаем UID, только если broker/customer-list подтверждает, что он наш
    реферал (см. BitgetAgentClient.is_referral). Иначе 422. Закрывает дыру, где
    stub-attach принимал любой UID.

    В отличие от MEXC, временного окна нет — фильтр Bitget по uid покрывает всю
    историю (probe 2026-06-01), так что и старые рефералы проходят verify.
    Повторное подключение уже-active того же UID verify пропускает.
    """
    existing = (
        await session.execute(
            select(ExchangeAccount).where(
                ExchangeAccount.user_id == user.id,
                ExchangeAccount.exchange == BITGET,
            )
        )
    ).scalar_one_or_none()

    if existing and existing.status == "active" and existing.exchange_uid != body.uid:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "К вашему аккаунту уже привязан другой Bitget UID",
        )
    if existing and existing.status == "active" and existing.exchange_uid == body.uid:
        return {"status": "active", "uid": existing.exchange_uid}

    if not (
        settings.bitget_api_key
        and settings.bitget_api_secret
        and settings.bitget_api_passphrase
    ):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Интеграция с Bitget временно недоступна",
        )

    try:
        async with BitgetAgentClient(
            api_key=settings.bitget_api_key,
            api_secret=settings.bitget_api_secret,
            passphrase=settings.bitget_api_passphrase,
            base_url=settings.bitget_base_url,
        ) as bg:
            is_ref = await bg.is_referral(body.uid)
    except BitgetError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Bitget не подтвердил привязку (код {exc.code})",
        ) from exc

    if not is_ref:
        if existing and existing.status != "active":
            await session.delete(existing)
            await session.commit()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Этот UID не привязан к нашей реферальной программе Bitget. "
            "Зарегистрируйтесь на Bitget по нашей ссылке или проверьте, что UID указан верно.",
        )

    if existing:
        existing.exchange_uid = body.uid
        existing.status = "active"
        if existing.invited_at is None:
            existing.invited_at = datetime.now(timezone.utc)
        await session.commit()
        return {"status": "active", "uid": existing.exchange_uid}

    account = ExchangeAccount(
        user_id=user.id,
        exchange=BITGET,
        exchange_uid=body.uid,
        status="active",
        invited_at=datetime.now(timezone.utc),
    )
    session.add(account)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Этот Bitget UID уже привязан к другому пользователю",
        ) from exc
    return {"status": "active", "uid": account.exchange_uid}


async def _connect_bydfi(
    session: AsyncSession,
    user: User,
    body: ConnectBody,
) -> dict:
    """Привязка BYDFi по числовому UID с РЕАЛЬНЫМ verify (аналог BingX/MEXC/Bitget).

    Принимаем UID, только если agent/validate_user подтверждает принадлежность
    (isSubordinate=true, см. BydfiAffiliateClient.is_referral). Иначе 422. Без
    временного окна — validate_user проверяет по всей истории. Повторное
    подключение уже-active того же UID verify пропускает.
    """
    existing = (
        await session.execute(
            select(ExchangeAccount).where(
                ExchangeAccount.user_id == user.id,
                ExchangeAccount.exchange == BYDFI,
            )
        )
    ).scalar_one_or_none()

    if existing and existing.status == "active" and existing.exchange_uid != body.uid:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "К вашему аккаунту уже привязан другой BYDFi UID",
        )
    if existing and existing.status == "active" and existing.exchange_uid == body.uid:
        return {"status": "active", "uid": existing.exchange_uid}

    if not settings.bydfi_api_key or not settings.bydfi_api_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Интеграция с BYDFi временно недоступна",
        )

    try:
        async with BydfiAffiliateClient(
            api_key=settings.bydfi_api_key,
            api_secret=settings.bydfi_api_secret,
            base_url=settings.bydfi_base_url,
        ) as bd:
            is_ref = await bd.is_referral(body.uid)
    except BydfiError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"BYDFi не подтвердил привязку (код {exc.code})",
        ) from exc

    if not is_ref:
        if existing and existing.status != "active":
            await session.delete(existing)
            await session.commit()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Этот UID не привязан к нашей реферальной программе BYDFi. "
            "Зарегистрируйтесь на BYDFi по нашей ссылке или проверьте, что UID указан верно.",
        )

    if existing:
        existing.exchange_uid = body.uid
        existing.status = "active"
        if existing.invited_at is None:
            existing.invited_at = datetime.now(timezone.utc)
        await session.commit()
        return {"status": "active", "uid": existing.exchange_uid}

    account = ExchangeAccount(
        user_id=user.id,
        exchange=BYDFI,
        exchange_uid=body.uid,
        status="active",
        invited_at=datetime.now(timezone.utc),
    )
    session.add(account)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Этот BYDFi UID уже привязан к другому пользователю",
        ) from exc
    return {"status": "active", "uid": account.exchange_uid}


@router.post("/{slug}/connect")
async def connect_exchange(
    slug: str,
    body: ConnectBody,
    tg_user: dict = Depends(telegram_user),
    session: AsyncSession = Depends(get_session),
):
    catalog = CATALOG_BY_SLUG.get(slug)
    if not catalog:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown exchange: {slug}")
    if not catalog["available"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{catalog['name']} ещё не подключена")

    user = await _current_user(session, tg_user)

    # Binance → привязка по email (apiReferral матчит рефералов по email, не по UID).
    if slug == BINANCE:
        return await _connect_binance(session, user, body)

    # Bitget → числовой UID с реальным verify (POST broker/customer-list), как BingX/
    # MEXC: принимаем UID, только если он действительно наш реферал. Иначе 422.
    if slug == BITGET:
        if not re.fullmatch(r"[0-9]{3,32}", body.uid):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Bitget UID должен быть числом",
            )
        return await _connect_bitget(session, user, body)

    # MEXC → числовой UID с реальным verify (affiliate/referral), как BingX: принимаем
    # UID, только если он действительно наш реферал. Иначе 422.
    if slug == MEXC:
        if not re.fullmatch(r"[0-9]{3,32}", body.uid):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "MEXC UID должен быть числом",
            )
        return await _connect_mexc(session, user, body)

    # BYDFi → числовой UID с реальным verify (agent/validate_user), как BingX/MEXC.
    if slug == BYDFI:
        if not re.fullmatch(r"[0-9]{3,32}", body.uid):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "BYDFi UID должен быть числом",
            )
        return await _connect_bydfi(session, user, body)

    # Биржа есть в каталоге, но без verify-ветки выше → подключение запрещаем.
    # Иначе вернулась бы дыра «принимаем любой UID». Новая available-биржа ОБЯЗАНА
    # иметь свой verify (как bingx/binance/bitget/mexc), прежде чем её включат.
    if slug != BINGX:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Подключение {catalog['name']} пока не настроено",
        )

    # BingX — UID должен быть числом (раньше это гарантировал pattern в ConnectBody).
    if not re.fullmatch(r"[0-9]{3,32}", body.uid):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "BingX UID должен быть числом",
        )

    existing = await session.execute(
        select(ExchangeAccount).where(
            ExchangeAccount.user_id == user.id,
            ExchangeAccount.exchange == BINGX,
        )
    )
    existing_account = existing.scalar_one_or_none()
    # 409 только если уже active с другим UID — менять active UID нельзя.
    # Если запись pending/failed — её можно перезаписать новым UID.
    if (
        existing_account
        and existing_account.status == "active"
        and existing_account.exchange_uid != body.uid
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "К вашему аккаунту уже привязан другой BingX UID",
        )

    if not settings.bingx_api_key or not settings.bingx_api_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Интеграция с BingX временно недоступна",
        )

    try:
        async with BingXAgentClient(
            api_key=settings.bingx_api_key,
            api_secret=settings.bingx_api_secret,
            base_url=settings.bingx_base_url,
            recv_window_ms=settings.bingx_recv_window_ms,
        ) as bx:
            # invite_relation_check, не superior_check: superior проверяет только
            # прямую связь с верхним agent, а наши юзеры висят под sub-агентом.
            relation = await bx.invite_relation_check(int(body.uid))
    except BingXError as exc:
        if exc.code == 100450:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Пользователь с таким UID не найден в BingX. Проверьте правильность UID.",
            ) from exc
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"BingX не подтвердил привязку (код {exc.code})",
        ) from exc

    invited = bool(relation.get("inviteResult"))

    if not invited:
        # Чистим мёртвую pending-запись от предыдущей попытки, если была.
        if existing_account and existing_account.status != "active":
            await session.delete(existing_account)
            await session.commit()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Этот UID не привязан к нашей реферальной программе. "
            "Зарегистрируйтесь на BingX по нашей ссылке или проверьте, что UID указан верно.",
        )

    if existing_account:
        existing_account.exchange_uid = body.uid
        existing_account.status = "active"
        if existing_account.invited_at is None:
            existing_account.invited_at = datetime.now(timezone.utc)
        await session.commit()
        return {
            "status": "active",
            "uid": existing_account.exchange_uid,
            "direct_invitation": relation.get("directInvitation"),
        }

    account = ExchangeAccount(
        user_id=user.id,
        exchange=BINGX,
        exchange_uid=body.uid,
        status="active",
        invited_at=datetime.now(timezone.utc),
    )
    session.add(account)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Этот BingX UID уже привязан к другому пользователю",
        ) from exc

    return {
        "status": "active",
        "uid": account.exchange_uid,
        "direct_invitation": relation.get("directInvitation"),
    }


@router.delete("/{slug}", status_code=status.HTTP_200_OK)
async def disconnect_exchange(
    slug: str,
    tg_user: dict = Depends(telegram_user),
    session: AsyncSession = Depends(get_session),
):
    """Отключить биржу от аккаунта юзера.

    Удаляется только запись `exchange_accounts(user_id, exchange)`. История
    начислений (`cashback_entries`) и выплат остаётся в БД — баланс на этой
    бирже доступен, если юзер подключит её снова с тем же или другим UID.

    Запрещено отключать биржу, если по ней есть pending/processing
    заявка на вывод — сначала её надо завершить через админку.
    """
    from app.models import Withdrawal

    user = await _current_user(session, tg_user)

    account = (
        await session.execute(
            select(ExchangeAccount).where(
                ExchangeAccount.user_id == user.id,
                ExchangeAccount.exchange == slug,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Эта биржа не подключена")

    pending = (
        await session.execute(
            select(Withdrawal.id).where(
                Withdrawal.user_id == user.id,
                Withdrawal.exchange == slug,
                Withdrawal.status.in_(["pending", "processing"]),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if pending is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "С этой биржи есть незавершённая заявка на вывод. Дождитесь её обработки.",
        )

    await session.delete(account)
    await session.commit()
    return {"deleted": True, "slug": slug}


@router.get("/bingx/status")
async def bingx_status(
    tg_user: dict = Depends(telegram_user),
    session: AsyncSession = Depends(get_session),
):
    user = await _current_user(session, tg_user)
    account = (
        await session.execute(
            select(ExchangeAccount).where(
                ExchangeAccount.user_id == user.id,
                ExchangeAccount.exchange == BINGX,
            )
        )
    ).scalar_one_or_none()
    if not account:
        return {"status": "not_connected"}
    return {"status": account.status, "uid": account.exchange_uid}
