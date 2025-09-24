from __future__ import annotations

import hmac
import hashlib
import time
from typing import Any, Dict, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


class AsterApiError(Exception):
    pass


class AsterClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret.encode("utf-8")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout_seconds)

    def _timestamp_ms(self) -> str:
        return str(int(time.time() * 1000))

    def _sign(self, payload: str) -> str:
        return hmac.new(self.api_secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def _auth_headers(self, query_string: str) -> Dict[str, str]:
        signature = self._sign(query_string)
        return {
            "X-API-KEY": self.api_key,
            "X-API-SIGNATURE": signature,
            "X-API-TIMESTAMP": query_string.split("timestamp=")[-1],
        }

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception_type((httpx.HTTPError, AsterApiError)),
    )
    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None) -> Any:
        params = params or {}
        # Simple common auth scheme: include timestamp in query, sign query
        if "timestamp" not in params:
            params["timestamp"] = self._timestamp_ms()
        # Build query string in stable order
        sorted_items = sorted(params.items(), key=lambda kv: kv[0])
        query_string = "&".join(f"{k}={v}" for k, v in sorted_items)
        headers = self._auth_headers(query_string)
        try:
            resp = self._client.request(method, path, params=params, json=json, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise AsterApiError(f"ASTER API error: {e.response.status_code} {e.response.text}") from e
        except httpx.HTTPError as e:
            raise e
        data = resp.json()
        # Optional API-level error check
        if isinstance(data, dict) and data.get("error"):
            raise AsterApiError(str(data["error"]))
        return data

    # Futures endpoints (names/paths may need to be adjusted to match docs)

    def get_positions(self, symbol: Optional[str] = None) -> Any:
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/futures/positions", params=params)

    def place_order(
        self,
        symbol: str,
        side: str,  # "BUY" or "SELL"
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
        return self._request("POST", "/futures/order", json=payload, params={})

    def set_leverage(self, symbol: str, leverage: int) -> Any:
        payload = {"symbol": symbol, "leverage": leverage}
        return self._request("POST", "/futures/leverage", json=payload, params={})

    def adjust_margin(self, symbol: str, amount: float) -> Any:
        payload = {"symbol": symbol, "amount": amount}
        return self._request("POST", "/futures/margin", json=payload, params={})

    def close(self) -> None:
        self._client.close()
