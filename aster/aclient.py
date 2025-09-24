from __future__ import annotations

import hmac
import hashlib
import time
from typing import Any, Dict, Optional

import httpx
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential, retry_if_exception_type


class AsterApiError(Exception):
    pass


class AsterAsyncClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str,
        timeout_seconds: float = 5.0,
        retries: int = 1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret.encode("utf-8")
        self.retries = max(0, int(retries))
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout_seconds)

    def _timestamp_ms(self) -> str:
        return str(int(time.time() * 1000))

    def _sign(self, payload: str) -> str:
        return hmac.new(self.api_secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    async def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None) -> Any:
        params = params or {}
        if "timestamp" not in params:
            params["timestamp"] = self._timestamp_ms()
        # Build query string in stable order (Binance style signing)
        sorted_items = sorted(params.items(), key=lambda kv: kv[0])
        query_string = "&".join(f"{k}={v}" for k, v in sorted_items)
        signature = self._sign(query_string)
        # Append signature to params
        signed_params = dict(params)
        signed_params["signature"] = signature
        headers = {"X-MBX-APIKEY": self.api_key}

        retry_cfg = AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(max(1, self.retries)),
            wait=wait_exponential(multiplier=0.3, min=0.3, max=2),
            retry=retry_if_exception_type((httpx.HTTPError, AsterApiError)),
        )

        async for attempt in retry_cfg:
            with attempt:
                resp = await self._client.request(method, path, params=signed_params, json=json, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict) and data.get("code") not in (None, 0) and data.get("msg"):
                    # Binance-like error body
                    raise AsterApiError(f"{data.get('code')}: {data.get('msg')}")
                if isinstance(data, dict) and data.get("error"):
                    raise AsterApiError(str(data["error"]))
                return data

    # Public request (no auth)
    async def _public_request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        params = params or {}
        resp = await self._client.request(method, path, params=params)
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return resp.text

    # Price endpoints
    async def get_symbol_price(self, symbol: str) -> float:
        data = await self._public_request("GET", "/fapi/v1/ticker/price", params={"symbol": symbol})
        if isinstance(data, dict) and "price" in data:
            try:
                return float(data["price"])
            except Exception as e:  # noqa: BLE001
                raise AsterApiError(f"Invalid price for {symbol}: {data}") from e
        raise AsterApiError(f"Unexpected price response for {symbol}: {data}")

    async def get_24h_change_percent(self, symbol: str) -> float:
        data = await self._public_request("GET", "/fapi/v1/ticker/24hr", params={"symbol": symbol})
        # Binance-compatible field name "priceChangePercent"
        if isinstance(data, dict) and "priceChangePercent" in data:
            try:
                return float(data["priceChangePercent"])
            except Exception as e:  # noqa: BLE001
                raise AsterApiError(f"Invalid 24h change for {symbol}: {data}") from e
        raise AsterApiError(f"Unexpected 24h ticker response for {symbol}: {data}")

    async def get_mark_price(self, symbol: str) -> float:
        # Binance-compatible mark price
        data = await self._public_request("GET", "/fapi/v1/premiumIndex", params={"symbol": symbol})
        if isinstance(data, dict) and "markPrice" in data:
            try:
                return float(data["markPrice"])
            except Exception as e:  # noqa: BLE001
                raise AsterApiError(f"Invalid mark price for {symbol}: {data}") from e
        raise AsterApiError(f"Unexpected mark price response for {symbol}: {data}")

    async def get_open_interest(self, symbol: str) -> float:
        # Binance-compatible open interest
        data = await self._public_request("GET", "/fapi/v1/openInterest", params={"symbol": symbol})
        if isinstance(data, dict) and "openInterest" in data:
            try:
                return float(data["openInterest"])
            except Exception as e:  # noqa: BLE001
                raise AsterApiError(f"Invalid open interest for {symbol}: {data}") from e
        raise AsterApiError(f"Unexpected open interest response for {symbol}: {data}")

    # Provided endpoints
    async def get_account_v4(self, recv_window: Optional[int] = None) -> Any:
        params: Dict[str, Any] = {}
        if recv_window is not None:
            params["recvWindow"] = recv_window
        return await self._request("GET", "/fapi/v4/account", params=params)

    async def get_balance_v2(self, recv_window: Optional[int] = None) -> Any:
        params: Dict[str, Any] = {}
        if recv_window is not None:
            params["recvWindow"] = recv_window
        return await self._request("GET", "/fapi/v2/balance", params=params)

    # Fallback positions via account
    async def get_positions(self, symbol: Optional[str] = None) -> Any:
        account = await self.get_account_v4()
        if symbol is None:
            return account.get("positions", []) if isinstance(account, dict) else []
        positions = account.get("positions", []) if isinstance(account, dict) else []
        return [p for p in positions if isinstance(p, dict) and p.get("symbol") == symbol]

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        reduce_only: bool = False,
    ) -> Any:
        payload = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity,
            "reduceOnly": reduce_only,
        }
        return await self._request("POST", "/futures/order", json=payload, params={})

    async def set_leverage(self, symbol: str, leverage: int) -> Any:
        payload = {"symbol": symbol, "leverage": leverage}
        return await self._request("POST", "/futures/leverage", json=payload, params={})

    async def adjust_margin(self, symbol: str, amount: float) -> Any:
        payload = {"symbol": symbol, "amount": amount}
        return await self._request("POST", "/futures/margin", json=payload, params={})

    async def aclose(self) -> None:
        await self._client.aclose()
