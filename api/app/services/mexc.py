"""MEXC Affiliate API client.

Программа MEXC Affiliate (кабинет affiliates.mexc.com): рефералы линкуются к
нашему inviteCode, ребейт-комиссии тянутся через /api/v3/rebate/affiliate/*.
Реферал идентифицируется по числовому `uid` — поэтому юзер при подключении
вводит UID (как Bitget). Verify неявный: кешбэк капает только если uid есть в
наших ребейт-данных (daily_mexc_sync).

Auth идентична MEXC Spot v3 (как Binance, БЕЗ passphrase): HMAC-SHA256 — query
string (вкл. timestamp ms, recvWindow) подписывается api_secret, подпись
добавляется как &signature=..., ключ в заголовке X-MEXC-APIKEY.

Формат ответа (подтверждён probe'ом 2026-06-01): envelope
{"success":true,"code":0,"message":null,"data":{...}} — code числовой 0;
пагинируемые data: {pageSize,totalCount,totalPage,currentPage,resultList:[...]}.
Ошибка — HTTP 4xx + {"code":<n>,"msg":"..."} (как Binance). _request устойчив
к обоим: при HTTP 200 и code 0/"0"/None возвращает data-узел.

Поля ВНУТРИ resultList (uid реферала, сумма ребейта) на probe не видны —
resultList был пуст (рефералов ещё нет). Суммы у MEXC в USDT (commission/detail
отдаёт totalCommissionUsdtAmount/totalTradeUsdtAmount). Имена полей записи
(uid, total/commission) заложены с fallback'ами в worker.daily_mexc_sync —
сверить повторным probe'ом при первом реферале, при расхождении поправить там.

Эндпоинты (base https://api.mexc.com):
  GET /api/v3/rebate/affiliate/commission — сводная комиссия (наш ребейт) по
      рефералам за период; startTime/endTime (ms) обязательны, окно ≤30 дней,
      пагинация page/page_size.
  GET /api/v3/rebate/affiliate/referral   — verify реферала: требует uid, сам
      проверяет принадлежность (code 0 = наш, 1035 = не наш, 601 = uid не передан).
      Используется при подключении биржи — см. is_referral().
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

log = logging.getLogger("mexc")

BASE_URL = "https://api.mexc.com"

# Коды affiliate/referral, означающие «uid НЕ наш реферал» (не инфра-ошибка).
# Подтверждено probe'ом 2026-06-01: code 1035 на заведомо-чужой uid. Connect
# трактует их как «не реферал» (422), а не как сбой (502). Расширить при первом
# реальном реферале, если найдутся другие «не наш»-коды.
_NOT_REFERRAL_CODES = {"1035"}


class MexcError(Exception):
    def __init__(
        self, code: int | str, msg: str, path: str = "", http_status: int | None = None
    ):
        self.code = code
        self.msg = msg
        self.path = path
        self.http_status = http_status
        super().__init__(f"MEXC {path} → http={http_status} code={code} msg={msg!r}")


class MexcAffiliateClient:
    """Async client for MEXC Affiliate (rebate) endpoints.

    Use as async context manager OR pass an external httpx.AsyncClient.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = BASE_URL,
        recv_window_ms: int = 5000,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
    ):
        self._key = api_key
        self._secret = api_secret.encode("utf-8")
        self._base = base_url.rstrip("/")
        self._recv_window = recv_window_ms
        self._client = client
        self._owns_client = client is None
        self._max_retries = max_retries

    async def __aenter__(self) -> "MexcAffiliateClient":
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
        self, method: str, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        if self._client is None:
            raise RuntimeError("MexcAffiliateClient used outside of context manager")

        params = dict(params or {})
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = self._recv_window
        query = self._build_query(params)
        signature = self._sign(query)
        url = f"{self._base}{path}?{query}&signature={signature}"
        headers = {"X-MEXC-APIKEY": self._key}

        last_exc: MexcError | None = None
        for attempt in range(self._max_retries):
            r = await self._client.request(method, url, headers=headers)
            try:
                data = r.json()
            except Exception as exc:
                if r.status_code == 200:
                    raise MexcError("http", "non-json 200 response", path, 200) from exc
                raise MexcError(
                    "http", f"non-json error status={r.status_code}", path, r.status_code
                ) from exc

            # Success: HTTP 200 и (нет envelope-code, либо code "0"/"200"). MEXC
            # spot v3 при успехе может вернуть и сырой объект/массив без "code".
            code = data.get("code") if isinstance(data, dict) else None
            if r.status_code == 200 and (code is None or str(code) in ("0", "200")):
                if isinstance(data, dict) and "data" in data:
                    return data["data"]
                return data

            msg = ""
            if isinstance(data, dict):
                msg = data.get("msg") or data.get("message") or ""
            last_exc = MexcError(
                code if code is not None else "http", msg, path, r.status_code
            )
            # Rate-limit: HTTP 429 / MEXC code 429 / 700003 → backoff и ретрай.
            if (
                r.status_code == 429 or str(code) in ("429", "700003")
            ) and attempt < self._max_retries - 1:
                delay = 2 ** attempt
                log.warning(
                    "mexc rate-limited path=%s attempt=%d sleeping=%ds",
                    path, attempt + 1, delay,
                )
                await asyncio.sleep(delay)
                continue
            raise last_exc
        assert last_exc is not None
        raise last_exc

    # ── Affiliate / rebate ─────────────────────────────────────────────────

    async def affiliate_commission(
        self,
        start_ms: int,
        end_ms: int,
        page: int = 1,
        page_size: int = 100,
        invite_code: str | None = None,
    ) -> Any:
        """GET /api/v3/rebate/affiliate/commission — наш ребейт по рефералам за период.

        startTime/endTime (ms) обязательны (с 2025-11-03), окно ≤30 дней. Пагинация
        page/page_size. Возвращает data-узел (обычно {resultList, totalPage,
        currentPage, ...} либо list). Поля записи (uid, total/commission, asset,
        time) — УТОЧНИТЬ probe'ом (см. докстринг модуля).
        """
        return await self._request(
            "GET",
            "/api/v3/rebate/affiliate/commission",
            {
                "startTime": start_ms,
                "endTime": end_ms,
                "page": page,
                "page_size": page_size,
                "invite_code": invite_code,
            },
        )

    async def affiliate_referral(
        self,
        start_ms: int,
        end_ms: int,
        uid: str | None = None,
        page: int = 1,
        page_size: int = 100,
        invite_code: str | None = None,
    ) -> Any:
        """GET /api/v3/rebate/affiliate/referral — проверка реферала по uid.

        ВАЖНО (probe 2026-06-01): эндпоинт требует `uid` и сам делает verify —
        code 0 = uid наш реферал, code 1035 = не наш, code 601 = uid не передан.
        Высокоуровневая обёртка — is_referral(); этот метод бросит MexcError на
        любой code≠0 (включая «не реферал»), поэтому для connect зови is_referral.
        """
        return await self._request(
            "GET",
            "/api/v3/rebate/affiliate/referral",
            {
                "startTime": start_ms,
                "endTime": end_ms,
                "uid": uid,
                "page": page,
                "page_size": page_size,
                "invite_code": invite_code,
            },
        )

    async def is_referral(self, uid: str, start_ms: int, end_ms: int) -> bool:
        """True, если `uid` привязан к нашему inviteCode (аналог BingX verify).

        affiliate/referral сам проверяет принадлежность uid — парсить resultList и
        угадывать имена полей не нужно. Семантика кода ответа (probe 2026-06-01):
          • code 0    → uid наш реферал (success)                → True;
          • code 1035 → uid НЕ наш реферал (или не существует)   → False;
          • code 601  → uid не передан (мы всегда передаём — сюда не доходим);
          • прочие коды / сетевые ошибки → пробрасываем (connect вернёт 502, fail-safe).

        Окно ≤30 дней (ограничение MEXC). Если у эндпоинта найдётся иной код для
        «не реферал», он уйдёт в 502 (не пустит, но сообщение менее точное) —
        расширить _NOT_REFERRAL_CODES при первом реальном реферале.
        """
        uid_str = str(uid).strip()
        if not uid_str:
            return False
        try:
            await self.affiliate_referral(
                start_ms=start_ms, end_ms=end_ms, uid=uid_str, page=1, page_size=100
            )
        except MexcError as exc:
            if str(exc.code) in _NOT_REFERRAL_CODES:
                return False
            raise
        return True
