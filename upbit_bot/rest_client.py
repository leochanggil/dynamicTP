from __future__ import annotations
import json, uuid, hashlib
from urllib.parse import urlencode
import aiohttp
import jwt

REST_URL = "https://api.upbit.com"

class UpbitREST:
    def __init__(self, session: aiohttp.ClientSession, access_key: str, secret_key: str):
        self.s = session
        self.ak = access_key
        self.sk = secret_key

    def _jwt(self, params: dict | None) -> str:
        payload = {"access_key": self.ak, "nonce": str(uuid.uuid4())}
        if params:
            query_string = urlencode([(k, str(v)) for k, v in sorted(params.items())])
            m = hashlib.sha512()
            m.update(query_string.encode())
            payload["query_hash"] = m.hexdigest()
            payload["query_hash_alg"] = "SHA512"
        return jwt.encode(payload, self.sk, algorithm="HS256")

    async def _req(self, method: str, path: str, params: dict | None = None) -> dict | list:
        url = REST_URL + path
        headers = {}
        if self.ak and self.sk:
            headers["Authorization"] = f"Bearer {self._jwt(params)}"

        if method in ("GET", "DELETE"):
            async with self.s.request(method, url, params=params, headers=headers, timeout=10) as r:
                t = await r.text()
                if r.status >= 400:
                    raise RuntimeError(f"{method} {path} {r.status}: {t}")
                return json.loads(t)
        else:
            async with self.s.request(method, url, json=params, headers=headers, timeout=10) as r:
                t = await r.text()
                if r.status >= 400:
                    raise RuntimeError(f"{method} {path} {r.status}: {t}")
                return json.loads(t)

    async def markets_all(self) -> list[dict]:
        return await self._req("GET", "/v1/market/all", {"isDetails": "false"})

    async def tickers(self, markets: list[str]) -> list[dict]:
        out = []
        for i in range(0, len(markets), 100):
            chunk = markets[i:i+100]
            res = await self._req("GET", "/v1/ticker", {"markets": ",".join(chunk)})
            out.extend(res if isinstance(res, list) else [res])
        return out

    async def post_order(self, params: dict) -> dict:
        return await self._req("POST", "/v1/orders", params)

    async def cancel_order(self, uuid_str: str) -> dict:
        return await self._req("DELETE", "/v1/order", {"uuid": uuid_str})

    async def get_order(self, uuid_str: str) -> dict:
        return await self._req("GET", "/v1/order", {"uuid": uuid_str})