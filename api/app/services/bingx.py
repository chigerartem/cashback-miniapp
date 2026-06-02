"""BingX Agent (Broker) API client.

Docs: docs/bingx_agent_api_reference.md
Auth: HMAC-SHA256 — query string signed with api_secret, header X-BX-APIKEY.
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

log = logging.getLogger("bingx")


class BingXError(Exception):
    def __init__(self, code: int | str, msg: str, path: str = ""):
        self.code = code
        self.msg = msg
        self.path = path
        super().__init__(f"BingX {path} → code={code} msg={msg!r}")


class BingXAgentClient:
    """Async client for BingX Agent (broker) API.

    Use as async context manager OR pass an external httpx.AsyncClient.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://open-api.bingx.com",
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

    async def __aenter__(self) -> "BingXAgentClient":
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

    async def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        if self._client is None:
            raise RuntimeError("BingXAgentClient used outside of context manager")

        params = dict(params or {})
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = self._recv_window
        query = self._build_query(params)
        signature = self._sign(query)
        url = f"{self._base}{path}?{query}&signature={signature}"
        headers = {"X-BX-APIKEY": self._key}

        last_exc: BingXError | None = None
        for attempt in range(self._max_retries):
            r = await self._client.request(method, url, headers=headers)
            try:
                data = r.json()
            except Exception as exc:
                raise BingXError("http", f"non-json response status={r.status_code}", path) from exc

            code = data.get("code")
            if code == 0:
                return data.get("data")

            last_exc = BingXError(code, data.get("msg", ""), path)
            if code == 100410 and attempt < self._max_retries - 1:
                delay = 2 ** attempt
                log.warning("bingx rate-limited path=%s attempt=%d sleeping=%ds", path, attempt + 1, delay)
                await asyncio.sleep(delay)
                continue
            raise last_exc
        assert last_exc is not None
        raise last_exc

    # ── Endpoints ─────────────────────────────────────────────────────────

    async def invite_account_list(
        self,
        page_index: int = 1,
        page_size: int = 100,
        start_ms: int | None = None,
        end_ms: int | None = None,
        last_uid: int | None = None,
    ) -> dict:
        """GET /openApi/agent/v1/account/inviteAccountList — list invited users."""
        return await self._request(
            "GET",
            "/openApi/agent/v1/account/inviteAccountList",
            {
                "pageIndex": page_index,
                "pageSize": page_size,
                "startTime": start_ms,
                "endTime": end_ms,
                "lastUid": last_uid,
            },
        )

    async def commission_data_list(
        self,
        start_ms: int,
        end_ms: int,
        page_index: int = 1,
        page_size: int = 100,
        uid: int | None = None,
        invitation_code: str | None = None,
        business_type: str | None = None,
    ) -> dict:
        """GET /openApi/agent/v2/reward/commissionDataList — daily commission per user.

        start_ms / end_ms are unix-ms timestamps. Max 7-day window (BingX changed
        from 30d → 7d at some point in 2026; YYYYMMDD format no longer accepted).
        """
        return await self._request(
            "GET",
            "/openApi/agent/v2/reward/commissionDataList",
            {
                "startTime": start_ms,
                "endTime": end_ms,
                "pageIndex": page_index,
                "pageSize": page_size,
                "uid": uid,
                "invitationCode": invitation_code,
                "businessType": business_type,
            },
        )

    async def invite_relation_check(self, uid: int) -> dict:
        """GET /openApi/agent/v1/account/inviteRelationCheck — full info for one UID."""
        return await self._request(
            "GET",
            "/openApi/agent/v1/account/inviteRelationCheck",
            {"uid": uid},
        )

    async def superior_check(self, uid: int) -> dict:
        """GET /openApi/agent/v1/account/superiorCheck — fast yes/no relation check."""
        return await self._request(
            "GET",
            "/openApi/agent/v1/account/superiorCheck",
            {"uid": uid},
        )

    async def referral_code_commissions(
        self,
        direct_invitation: bool = True,
        referral_code: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        page_index: int = 1,
        page_size: int = 100,
    ) -> dict:
        """GET /openApi/agent/v1/commissionDataList/referralCode — daily aggregate per code."""
        return await self._request(
            "GET",
            "/openApi/agent/v1/commissionDataList/referralCode",
            {
                "directInvitation": "true" if direct_invitation else "false",
                "referralCode": referral_code,
                "startTime": start_ms,
                "endTime": end_ms,
                "pageIndex": page_index,
                "pageSize": page_size,
            },
        )
