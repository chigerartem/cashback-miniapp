"""BYDFi Affiliate (Agent/KOL) API client.

Программа BYDFi Affiliate: рефералы линкуются к нашему agent-аккаунту (inviteCode).
Реферал идентифицируется по UID (validate_user принимает и email) — поэтому при
подключении юзер вводит UID, как Bitget/MEXC.

Base: **https://api.bydfi.com/api** — префикс `/api` ОБЯЗАТЕЛЕН (без него nginx 404;
сам `api.bydfi.com/v1/...` не существует). Подтверждено probe'ом 2026-06-01.

Auth (dok: developers.bydfi.com/en/signature) — заголовочный, подпись hex-HMAC-SHA256:
заголовки X-API-KEY / X-API-TIMESTAMP (ms) / X-API-SIGNATURE, Content-Type application/json,
Accept-Language en-US. Подпись = hex(HMAC_SHA256(secret, accessKey + timestamp +
queryString + body)), где queryString — параметры после `?` в порядке запроса (без
ведущего `?`), body — тело (для GET пусто).

Формат ответа (probe 2026-06-01): {"code":200,"message":"success","data":...}; code≠200
— ошибка (HTTP 200 + envelope, либо HTML 404 при неверном пути).

Эндпоинты (base .../api):
  GET /v1/agent/validate_user?account=<uid|email> — VERIFY: data.isSubordinate (bool).
      Без временного окна — проверка по всей истории. Это основной verify для connect.
  GET /v1/agent/affiliate_commission — ребейты по рефералам (uid, commission, fee, coin,
      productType, date в ms); startTime/endTime окно ≤180 дней.
  GET /v1/agent/teams — наш agent-аккаунт (spotRate/swapRate, refer, inviteUrl).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

log = logging.getLogger("bydfi")

BASE_URL = "https://api.bydfi.com/api"
_OK_CODE = "200"


class BydfiError(Exception):
    def __init__(
        self, code: int | str, msg: str, path: str = "", http_status: int | None = None
    ):
        self.code = code
        self.msg = msg
        self.path = path
        self.http_status = http_status
        super().__init__(f"BYDFi {path} → http={http_status} code={code} msg={msg!r}")


class BydfiAffiliateClient:
    """Async client for BYDFi Affiliate (agent) endpoints.

    Use as async context manager OR pass an external httpx.AsyncClient.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = BASE_URL,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
    ):
        self._key = api_key
        self._secret = api_secret.encode("utf-8")
        self._base = base_url.rstrip("/")
        self._client = client
        self._owns_client = client is None
        self._max_retries = max_retries

    async def __aenter__(self) -> "BydfiAffiliateClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _sign(self, ts: str, query_string: str, body: str = "") -> str:
        msg = self._key + ts + query_string + body
        return hmac.new(self._secret, msg.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _build_query(params: dict[str, Any]) -> str:
        return urlencode([(k, str(v)) for k, v in params.items() if v is not None])

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body_dict: dict[str, Any] | None = None,
    ) -> Any:
        if self._client is None:
            raise RuntimeError("BydfiAffiliateClient used outside of context manager")

        method = method.upper()
        # queryString для подписи = в том же порядке, что и в URL (без ведущего '?').
        query = self._build_query(params or {})
        request_path = f"{path}?{query}" if query else path
        url = f"{self._base}{request_path}"
        body_str = json.dumps(body_dict, separators=(",", ":")) if body_dict else ""

        last_exc: BydfiError | None = None
        for attempt in range(self._max_retries):
            ts = str(int(time.time() * 1000))
            headers = {
                "X-API-KEY": self._key,
                "X-API-TIMESTAMP": ts,
                "X-API-SIGNATURE": self._sign(ts, query, body_str),
                "Content-Type": "application/json",
                "Accept-Language": "en-US",
            }
            r = await self._client.request(
                method, url, headers=headers, content=(body_str or None)
            )
            try:
                data = r.json()
            except Exception as exc:
                raise BydfiError(
                    "http", f"non-json status={r.status_code}", path, r.status_code
                ) from exc

            code = data.get("code") if isinstance(data, dict) else None
            if r.status_code == 200 and str(code) == _OK_CODE:
                return data.get("data") if isinstance(data, dict) else data

            msg = (
                (data.get("message") or data.get("msg") or "")
                if isinstance(data, dict)
                else str(data)
            )
            last_exc = BydfiError(
                code if code is not None else "http", msg, path, r.status_code
            )
            if (r.status_code == 429 or str(code) == "429") and attempt < self._max_retries - 1:
                delay = 2 ** attempt
                log.warning("bydfi rate-limited path=%s attempt=%d sleeping=%ds", path, attempt + 1, delay)
                await asyncio.sleep(delay)
                continue
            raise last_exc
        assert last_exc is not None
        raise last_exc

    # ── Affiliate / agent ──────────────────────────────────────────────────

    async def validate_user(self, account: str) -> dict:
        """GET /v1/agent/validate_user?account=<uid|email> → data {isSubordinate, ...}."""
        data = await self._request(
            "GET", "/v1/agent/validate_user", {"account": account}
        )
        return data if isinstance(data, dict) else {}

    async def is_referral(self, account: str) -> bool:
        """True, если `account` (UID или email) — наш прямой реферал (аналог BingX verify).

        validate_user сам проверяет принадлежность (data.isSubordinate, probe 2026-06-01:
        фейк → false). Без временного окна — проверка по всей истории.
        """
        acc = str(account).strip()
        if not acc:
            return False
        data = await self.validate_user(acc)
        return bool(data.get("isSubordinate"))

    async def affiliate_commission(
        self,
        start_ms: int,
        end_ms: int,
        uid: str | None = None,
        coin: str | None = None,
        product_type: str | None = None,
        page: int = 1,
        rows: int = 100,
    ) -> list[dict]:
        """GET /v1/agent/affiliate_commission — ребейты по рефералам за период.

        Окно startTime/endTime ≤180 дней. Запись: {coin, commission (выплачено НАМ),
        fee (net trading fee), date (ms), productType (SPOT/SWAP), uid}.
        """
        data = await self._request(
            "GET",
            "/v1/agent/affiliate_commission",
            {
                "uid": uid,
                "startTime": start_ms,
                "endTime": end_ms,
                "coin": coin,
                "productType": product_type,
                "page": page,
                "rows": rows,
            },
        )
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):
            rows_ = data.get("list") or data.get("data") or []
            return [r for r in rows_ if isinstance(r, dict)] if isinstance(rows_, list) else []
        return []

    async def teams(self) -> dict:
        """GET /v1/agent/teams — наш agent-аккаунт (spotRate/swapRate, refer, inviteUrl)."""
        data = await self._request("GET", "/v1/agent/teams")
        return data if isinstance(data, dict) else {}
