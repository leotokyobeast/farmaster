from __future__ import annotations

import json
import math
import time
from typing import Any, Dict, Optional

import httpx
from eth_abi import encode
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3


class AsterEvmClient:
    def __init__(self, base_url: str, user: str, signer: str, private_key: str, timeout_seconds: float = 8.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.user = Web3.to_checksum_address(user)
        self.signer = Web3.to_checksum_address(signer)
        self.private_key = private_key
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout_seconds)

    def _nonce(self) -> int:
        return math.trunc(time.time() * 1000000)

    def _now_ms(self) -> int:
        return int(round(time.time() * 1000))

    def _trim_dict(self, payload: Dict[str, Any]) -> Dict[str, str]:
        # Convert nested structures to deterministic strings
        def _normalize(value: Any) -> str:
            if isinstance(value, dict):
                return json.dumps({k: _normalize(v) for k, v in value.items()}, sort_keys=True)
            if isinstance(value, list):
                return json.dumps([_normalize(v) for v in value])
            return str(value)

        return {k: _normalize(v) for k, v in payload.items()}

    def _prepare_and_sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        body: Dict[str, Any] = {k: v for k, v in params.items() if v is not None}
        body["recvWindow"] = 50000
        body["timestamp"] = self._now_ms()
        nonce = self._nonce()

        trimmed = self._trim_dict(body)
        json_str = json.dumps(trimmed, sort_keys=True).replace(" ", "").replace("'", '"')
        encoded = encode(['string', 'address', 'address', 'uint256'], [json_str, self.user, self.signer, nonce])
        keccak_hex = Web3.keccak(encoded).hex()

        signable_msg = encode_defunct(hexstr=keccak_hex)
        signed_message = Account.sign_message(signable_message=signable_msg, private_key=self.private_key)

        body["nonce"] = nonce
        body["user"] = self.user
        body["signer"] = self.signer
        body["signature"] = '0x' + signed_message.signature.hex()
        return body

    async def _send(self, url: str, method: str, params: Dict[str, Any]) -> Any:
        path = self.base_url + url
        if method.upper() == 'POST':
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': 'PythonApp/1.0'
            }
            resp = await self._client.post(path, data=params, headers=headers)
        elif method.upper() == 'GET':
            resp = await self._client.get(path, params=params)
        elif method.upper() == 'DELETE':
            resp = await self._client.delete(path, data=params)
        else:
            raise ValueError(f"Unsupported method {method}")
        resp.raise_for_status()
        # Try JSON, otherwise return text
        try:
            return resp.json()
        except Exception:
            return resp.text

    async def call(self, url: str, method: str, params: Dict[str, Any]) -> Any:
        signed = self._prepare_and_sign(params)
        return await self._send(url, method, signed)

    # Convenience wrappers
    async def place_order(self, symbol: str, side: str, order_type: str, quantity: str, price: Optional[float] = None,
                          time_in_force: Optional[str] = None, reduce_only: Optional[bool] = None,
                          position_side: Optional[str] = None) -> Any:
        params: Dict[str, Any] = {
            'symbol': symbol,
            'positionSide': position_side or 'BOTH',
            'type': order_type,
            'side': side,
            'timeInForce': time_in_force,
            'quantity': quantity,
            'price': price,
            'reduceOnly': reduce_only,
        }
        return await self.call('/fapi/v3/order', 'POST', params)

    async def get_order(self, symbol: str, order_id: Optional[int] = None, orig_client_order_id: Optional[str] = None,
                        side: Optional[str] = None, order_type: Optional[str] = None) -> Any:
        params: Dict[str, Any] = {
            'symbol': symbol,
            'orderId': order_id,
            'origClientOrderId': orig_client_order_id,
            'side': side,
            'type': order_type,
        }
        return await self.call('/fapi/v3/order', 'GET', params)

    async def aclose(self) -> None:
        await self._client.aclose()
