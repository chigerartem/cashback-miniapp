"""Bitget Agent/Affiliate API client.

Программа Bitget Agent (affiliate): рефералы линкуются к нашему agent-аккаунту,
ребейт-комиссии тянутся через /api/v2/broker/customer-commissions. В отличие от
Binance (email), Bitget идентифицирует рефералов по **UID** — в записи есть
`uid` + `rebateAmount` (наш ребейт). Поэтому юзер при подключении вводит UID.

Auth (как у OKX): четыре заголовка ACCESS-KEY / ACCESS-SIGN / ACCESS-TIMESTAMP /
ACCESS-PASSPHRASE. Подпись = base64(HMAC-SHA256(secret, prehash)), где
prehash = timestamp + METHOD + requestPath(+?query) + body. Для GET body="".
Ответ — конверт {"code":"00000","msg":"success","data":...}; code≠"00000" — ошибка.

Эндпоинты (Bitget v2, base https://api.bitget.com):
  GET  /api/v2/broker/customer-commissions — ребейты по рефералам (uid, rebateAmount)
  POST /api/v2/broker/customer-list        — наши рефералы (verify по uid); POST, не
       GET! Серверный фильтр по uid точный, без временного окна — см. is_referral().
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

log = logging.getLogger("bitget")

BASE_URL = "https://api.bitget.com"
_OK_CODE = "00000"


class BitgetError(Exception):
    def __init__(
        self, code: int | str, msg: str, path: str = "", http_status: int | None = None
    ):
        self.code = code
        self.msg = msg
        self.path = path
        self.http_status = http_status
        super().__init__(f"Bitget {path} → http={http_status} code={code} msg={msg!r}")


class BitgetAgentClient:
    """Async client for Bitget Agent/Affiliate endpoints.

    Use as async context manager OR pass an external httpx.AsyncClient.
    Requires api_key + api_secret + passphrase (все три обязательны).
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str,
        base_url: str = BASE_URL,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
    ):
        self._key = api_key
        self._secret = api_secret.encode("utf-8")
        self._passphrase = passphrase
        self._base = base_url.rstrip("/")
        self._client = client
        self._owns_client = client is None
        self._max_retries = max_retries

    async def __aenter__(self) -> "BitgetAgentClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _sign(self, prehash: str) -> str:
        digest = hmac.new(self._secret, prehash.encode("utf-8"), hashlib.sha256).digest()
        return base64.b64encode(digest).decode("utf-8")

    @staticmethod
    def _build_query(params: dict[str, Any]) -> str:
        items = [(k, str(v)) for k, v in params.items() if v is not None]
        return urlencode(items)

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        if self._client is None:
            raise RuntimeError("BitgetAgentClient used outside of context manager")

        method = method.upper()
        query = self._build_query(params or {})
        request_path = f"{path}?{query}" if query else path
        url = f"{self._base}{request_path}"

        # POST-тело подписывается целиком (prehash = ts+METHOD+path+body). Для GET
        # body=None → body_str="" → подпись и запрос идентичны прежним (GET без тела).
        body_str = ""
        if body is not None:
            payload = {k: v for k, v in body.items() if v is not None}
            body_str = json.dumps(payload, separators=(",", ":")) if payload else "{}"

        last_exc: BitgetError | None = None
        for attempt in range(self._max_retries):
            # Подпись пересчитывается на каждой попытке — timestamp свежий.
            ts = str(int(time.time() * 1000))
            prehash = ts + method + request_path + body_str
            headers = {
                "ACCESS-KEY": self._key,
                "ACCESS-SIGN": self._sign(prehash),
                "ACCESS-TIMESTAMP": ts,
                "ACCESS-PASSPHRASE": self._passphrase,
                "Content-Type": "application/json",
                "locale": "en-US",
            }
            r = await self._client.request(
                method, url, headers=headers, content=(body_str or None)
            )
            try:
                data = r.json()
            except Exception as exc:
                raise BitgetError(
                    "http", f"non-json status={r.status_code}", path, r.status_code
                ) from exc

            code = str(data.get("code")) if isinstance(data, dict) else "http"
            if r.status_code == 200 and code == _OK_CODE:
                return data.get("data") if isinstance(data, dict) else data

            msg = data.get("msg", "") if isinstance(data, dict) else str(data)
            last_exc = BitgetError(code, msg, path, r.status_code)
            # HTTP 429 / Bitget too-many-requests → backoff и ретрай.
            if (r.status_code == 429 or code in ("429", "30007")) and attempt < self._max_retries - 1:
                delay = 2**attempt
                log.warning(
                    "bitget rate-limited path=%s attempt=%d sleeping=%ds",
                    path, attempt + 1, delay,
                )
                await asyncio.sleep(delay)
                continue
            raise last_exc
        assert last_exc is not None
        raise last_exc

    # ── Agent / Affiliate ──────────────────────────────────────────────────

    async def agent_customer_commissions(
        self,
        start_ms: int | None = None,
        end_ms: int | None = None,
        uid: str | None = None,
        id_less_than: str | None = None,
        limit: int = 100,
        coin: str | None = None,
    ) -> tuple[list[dict], str | None]:
        """GET /api/v2/broker/customer-commissions — ребейты по нашим рефералам.

        Запись содержит `uid` реферала и `rebateAmount` (комиссия, которую
        получили МЫ). Ответ (подтверждён probe'ом 2026-05-29):
        data = {"commissionList": [...], "endId": <cursor>}. Пагинация cursor-
        style: следующий запрос с idLessThan=endId, пока commissionList не пуст.
        Окно — startTime/endTime в ms. Возвращает (записи, endId-курсор).
        """
        data = await self._request(
            "GET",
            "/api/v2/broker/customer-commissions",
            {
                "startTime": start_ms,
                "endTime": end_ms,
                "uid": uid,
                "idLessThan": id_less_than,
                "limit": limit,
                "coin": coin,
            },
        )
        if isinstance(data, dict):
            records = data.get("commissionList") or data.get("list") or []
            return (records if isinstance(records, list) else []), data.get("endId")
        return (data if isinstance(data, list) else []), None

    async def agent_customer_list(
        self,
        uid: str | None = None,
        referral_code: str | None = None,
        page_no: int = 1,
        page_size: int = 100,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[dict]:
        """POST /api/v2/broker/customer-list — наши рефералы (опц. фильтр по uid).

        ВАЖНО (probe 2026-06-01): это POST, не GET. Серверный фильтр по uid точный
        (чужой/несуществующий → []). startTime/endTime фильтруют по registerTime —
        для verify их НЕ задаём (иначе реферал старше окна выпадет). Запись:
        {"uid": "...", "registerTime": "<ms>"}.
        """
        data = await self._request(
            "POST",
            "/api/v2/broker/customer-list",
            body={
                "uid": uid,
                "referralCode": referral_code,
                "pageNo": page_no,
                "pageSize": page_size,
                "startTime": start_ms,
                "endTime": end_ms,
            },
        )
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):
            rows = data.get("list") or data.get("customerList") or []
            return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        return []

    async def is_referral(self, uid: str) -> bool:
        """True, если `uid` — наш реферал (аналог BingX verify).

        POST customer-list с фильтром по uid (без временного окна — фильтр
        покрывает всю историю, probe 2026-06-01). Серверный фильтр точный; доп.
        клиентская сверка uid == запись — на случай, если фильтр ослабнет.
        """
        uid_str = str(uid).strip()
        if not uid_str:
            return False
        rows = await self.agent_customer_list(uid=uid_str, page_no=1, page_size=100)
        return any(str(r.get("uid") or "").strip() == uid_str for r in rows)
