"""Binance API-Agent (apiReferral / Binance Link) client.

Программа Binance Link / API-Partner: рефералы линкуются к нашему apiAgentCode,
ребейт-комиссии тянутся через /sapi/v1/apiReferral/* (spot) и /fapi/v1/apiReferral/*
(futures). Подтверждено probe'ом: эти ключи (ReadOnly) видят apiReferral (HTTP 200).

ВАЖНО: в отличие от BingX, рефералы здесь идентифицируются по `customerId`/`email`,
а НЕ по UID. В rebate-записи нет Binance UID — только customerId, email, income, asset.

Auth: HMAC-SHA256 — query string (вкл. timestamp, recvWindow) подписывается
api_secret, подпись добавляется как &signature=..., ключ в заголовке X-MBX-APIKEY.
Success → HTTP 200 + сырой JSON. Error → HTTP 4xx + {"code":-xxxx,"msg":"..."}.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

log = logging.getLogger("binance")

SPOT_BASE = "https://api.binance.com"
FAPI_BASE = "https://fapi.binance.com"


class BinanceError(Exception):
    def __init__(self, code: int | str, msg: str, path: str = "", http_status: int | None = None):
        self.code = code
        self.msg = msg
        self.path = path
        self.http_status = http_status
        super().__init__(f"Binance {path} → http={http_status} code={code} msg={msg!r}")


class BinanceAgentClient:
    """Async client for Binance API-Agent (apiReferral) endpoints.

    Use as async context manager OR pass an external httpx.AsyncClient.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = SPOT_BASE,
        fapi_url: str = FAPI_BASE,
        recv_window_ms: int = 5000,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
    ):
        self._key = api_key
        self._secret = api_secret.encode("utf-8")
        self._base = base_url.rstrip("/")
        self._fapi = fapi_url.rstrip("/")
        self._recv_window = recv_window_ms
        self._client = client
        self._owns_client = client is None
        self._max_retries = max_retries

    async def __aenter__(self) -> "BinanceAgentClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _sign(self, query: str) -> str:
        return hmac.new(self._secret, query.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _build_query(params: dict[str, Any]) -> str:
        items = [(k, str(v)) for k, v in params.items() if v is not None]
        return urlencode(items)

    async def _request(
        self, method: str, base: str, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        if self._client is None:
            raise RuntimeError("BinanceAgentClient used outside of context manager")

        params = dict(params or {})
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = self._recv_window
        query = self._build_query(params)
        signature = self._sign(query)
        url = f"{base}{path}?{query}&signature={signature}"
        headers = {"X-MBX-APIKEY": self._key}

        last_exc: BinanceError | None = None
        for attempt in range(self._max_retries):
            r = await self._client.request(method, url, headers=headers)
            try:
                data = r.json()
            except Exception as exc:
                if r.status_code == 200:
                    raise BinanceError("http", "non-json 200 response", path, 200) from exc
                raise BinanceError("http", f"non-json error status={r.status_code}", path, r.status_code) from exc

            if r.status_code == 200:
                return data

            # error envelope: {"code": -xxxx, "msg": "..."}
            code = data.get("code") if isinstance(data, dict) else "http"
            msg = data.get("msg", "") if isinstance(data, dict) else str(data)
            last_exc = BinanceError(code, msg, path, r.status_code)
            # -1003 too many requests / HTTP 429 / 418 → backoff and retry
            if (r.status_code in (429, 418) or code == -1003) and attempt < self._max_retries - 1:
                delay = 2 ** attempt
                log.warning("binance rate-limited path=%s attempt=%d sleeping=%ds", path, attempt + 1, delay)
                await asyncio.sleep(delay)
                continue
            raise last_exc
        assert last_exc is not None
        raise last_exc

    # ── Health / permissions ──────────────────────────────────────────────

    async def api_restrictions(self) -> dict:
        """GET /sapi/v1/account/apiRestrictions — key permissions (enableReading, ...)."""
        return await self._request("GET", self._base, "/sapi/v1/account/apiRestrictions")

    # ── Spot apiReferral ──────────────────────────────────────────────────

    async def spot_rebate_recent_record(
        self,
        limit: int = 500,
        start_ms: int | None = None,
        end_ms: int | None = None,
        customer_id: str | None = None,
    ) -> list[dict]:
        """GET /sapi/v1/apiReferral/rebate/recentRecord — наши ребейты по рефералам.

        limit ≤ 500 (mandatory). Окно ≤ 7 дней; без start/end — последние 7 дней.
        Запись: {customerId, email, income, asset, symbol, time, orderId, tradeId}.
        `income` — комиссия, которую получили МЫ (в `asset`).
        """
        data = await self._request(
            "GET",
            self._base,
            "/sapi/v1/apiReferral/rebate/recentRecord",
            {
                "limit": limit,
                "startTime": start_ms,
                "endTime": end_ms,
                "customerId": customer_id,
            },
        )
        return data if isinstance(data, list) else []

    async def if_new_user(self, api_agent_code: str) -> dict:
        """GET /sapi/v1/apiReferral/ifNewUser — {apiAgentCode, rebateWorking, ifNewUser, referrerId}."""
        return await self._request(
            "GET",
            self._base,
            "/sapi/v1/apiReferral/ifNewUser",
            {"apiAgentCode": api_agent_code},
        )

    async def spot_customization(
        self, customer_id: str | None = None, email: str | None = None
    ) -> list[dict]:
        """GET /sapi/v1/apiReferral/customization — маппинг customerId↔email.

        customerId и email одновременно слать нельзя. Без параметров — весь список.
        """
        data = await self._request(
            "GET",
            self._base,
            "/sapi/v1/apiReferral/customization",
            {"customerId": customer_id, "email": email},
        )
        return data if isinstance(data, list) else []

    # ── Futures apiReferral ───────────────────────────────────────────────

    async def futures_rebate_vol(
        self, start_ms: int | None = None, end_ms: int | None = None, limit: int = 1000
    ) -> list[dict]:
        """GET /fapi/v1/apiReferral/rebateVol — фьючерсный ребейт-объём по дням."""
        data = await self._request(
            "GET",
            self._fapi,
            "/fapi/v1/apiReferral/rebateVol",
            {"startTime": start_ms, "endTime": end_ms, "limit": limit},
        )
        return data if isinstance(data, list) else []

    async def futures_trade_vol(
        self, start_ms: int | None = None, end_ms: int | None = None, limit: int = 1000
    ) -> list[dict]:
        """GET /fapi/v1/apiReferral/tradeVol — торговый объём рефералов по дням."""
        data = await self._request(
            "GET",
            self._fapi,
            "/fapi/v1/apiReferral/tradeVol",
            {"startTime": start_ms, "endTime": end_ms, "limit": limit},
        )
        return data if isinstance(data, list) else []

    async def futures_customization(
        self, customer_id: str | None = None, email: str | None = None
    ) -> dict:
        """GET /fapi/v1/apiReferral/customization — {rows:[{customerId,email}], total}."""
        return await self._request(
            "GET",
            self._fapi,
            "/fapi/v1/apiReferral/customization",
            {"customerId": customer_id, "email": email},
        )

    # ── Verify (привязка) ─────────────────────────────────────────────────

    async def is_referral_email(self, email: str) -> bool:
        """True, если `email` — наш реферал (аналог BingX verify, для connect).

        В отличие от UID-бирж, Binance матчит рефералов по email. Серверный фильтр
        customization по email этому агентскому ключу НЕдоступен (HTTP 403, probe
        2026-06-01) — поэтому тянем ВЕСЬ customization-маппинг (spot list +
        futures rows) и матчим email локально (case-insensitive).

        Ошибки API пробрасываются (BinanceError) — connect обязан трактовать их как
        502 (fail-safe), а НЕ как «не реферал». Пагинации у customization нет; если
        список рефералов вырастет до лимита — добавить постраничную выборку.
        """
        target = (email or "").strip().lower()
        if not target:
            return False
        spot = await self.spot_customization()  # list[{customerId, email}]
        if any(str(r.get("email") or "").strip().lower() == target for r in spot):
            return True
        fut = await self.futures_customization()  # {rows: [{customerId, email}], total}
        rows = fut.get("rows") if isinstance(fut, dict) else None
        if isinstance(rows, list):
            return any(str(r.get("email") or "").strip().lower() == target for r in rows)
        return False
