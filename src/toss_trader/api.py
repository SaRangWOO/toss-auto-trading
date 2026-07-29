from __future__ import annotations

import gzip
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


BASE_URL = "https://openapi.tossinvest.com"


class TossApiError(RuntimeError):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        request_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"Toss OpenAPI {status} {code}: {message}")
        self.status = status
        self.code = code
        self.request_id = request_id
        self.data = data or {}


@dataclass
class Token:
    access_token: str
    expires_at: float


class TossClient:
    """Small standard-library client for Toss Securities OpenAPI v1.2.4."""

    _GROUP_TPS = {
        "AUTH": 4,
        "ACCOUNT": 1,
        "ASSET": 4,
        "STOCK": 4,
        "MARKET_INFO": 2,
        "MARKET_DATA": 8,
        "MARKET_DATA_CHART": 4,
        "RANKING": 4,
        "ORDER": 2,
        "ORDER_HISTORY": 4,
        "ORDER_INFO": 2,
    }

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        account_seq: int | None = None,
        timeout_seconds: int = 15,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.account_seq = account_seq
        self.timeout_seconds = timeout_seconds
        self._token: Token | None = None
        self._last_call: dict[str, float] = {}

    def _throttle(self, group: str) -> None:
        tps = self._GROUP_TPS[group]
        minimum_interval = 1 / tps
        now = time.monotonic()
        wait = minimum_interval - (now - self._last_call.get(group, 0.0))
        if wait > 0:
            time.sleep(wait)
        self._last_call[group] = time.monotonic()

    @staticmethod
    def _decode_body(raw: bytes, content_encoding: str | None) -> str:
        encoding = (content_encoding or "").lower()
        try:
            if raw.startswith(b"\x1f\x8b") or "gzip" in encoding:
                raw = gzip.decompress(raw)
            elif "deflate" in encoding:
                raw = zlib.decompress(raw)
        except (EOFError, OSError, zlib.error):
            pass
        return raw.decode("utf-8", errors="replace")

    def issue_token(self, force: bool = False) -> str:
        if (
            not force
            and self._token is not None
            and self._token.expires_at - time.time() > 60
        ):
            return self._token.access_token
        if not self.client_id or not self.client_secret:
            raise ValueError(
                "TOSS_CLIENT_ID와 TOSS_CLIENT_SECRET을 .env에 설정해야 합니다."
            )
        self._throttle("AUTH")
        encoded = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        ).encode("ascii")
        request = urllib.request.Request(
            BASE_URL + "/oauth2/token",
            data=encoded,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        payload, _ = self._open(request, authenticated=False, group="AUTH")
        self._token = Token(
            access_token=payload["access_token"],
            expires_at=time.time() + int(payload["expires_in"]),
        )
        return self._token.access_token

    def _open(
        self,
        request: urllib.request.Request,
        *,
        authenticated: bool,
        group: str,
        retry: int = 0,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        if authenticated:
            request.add_header("Authorization", f"Bearer {self.issue_token()}")
        self._throttle(group)
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                raw = self._decode_body(
                    response.read(), response.headers.get("Content-Encoding")
                )
                headers = {key.lower(): value for key, value in response.headers.items()}
                return json.loads(raw), headers
        except urllib.error.HTTPError as exc:
            raw = self._decode_body(
                exc.read(), exc.headers.get("Content-Encoding")
            )
            try:
                error_payload = json.loads(raw).get("error", {})
            except json.JSONDecodeError:
                error_payload = {}
            code = str(error_payload.get("code", "http-error"))
            message = str(error_payload.get("message", raw[:300] or exc.reason))
            request_id = error_payload.get("requestId") or exc.headers.get("X-Request-Id")
            error_data = error_payload.get("data")
            if exc.code == 401 and authenticated and retry == 0:
                self.issue_token(force=True)
                return self._open(
                    request, authenticated=True, group=group, retry=retry + 1
                )
            if exc.code == 429 and retry < 3:
                retry_after = float(exc.headers.get("Retry-After", 2**retry))
                time.sleep(retry_after + random.uniform(0.05, 0.25))
                return self._open(
                    request,
                    authenticated=authenticated,
                    group=group,
                    retry=retry + 1,
                )
            if exc.code >= 500 and retry < 3:
                time.sleep((2**retry) + random.uniform(0.05, 0.25))
                return self._open(
                    request,
                    authenticated=authenticated,
                    group=group,
                    retry=retry + 1,
                )
            raise TossApiError(
                exc.code,
                code,
                message,
                request_id,
                error_data if isinstance(error_data, dict) else None,
            ) from exc
        except urllib.error.URLError as exc:
            if retry < 2:
                time.sleep(2**retry)
                return self._open(
                    request,
                    authenticated=authenticated,
                    group=group,
                    retry=retry + 1,
                )
            raise RuntimeError(f"Toss OpenAPI 네트워크 오류: {exc.reason}") from exc

    def _request(
        self,
        method: str,
        path: str,
        group: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        account: bool = False,
    ) -> dict[str, Any]:
        url = BASE_URL + path
        if query:
            clean_query = {
                key: str(value).lower() if isinstance(value, bool) else value
                for key, value in query.items()
                if value is not None
            }
            url += "?" + urllib.parse.urlencode(clean_query)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if account:
            if self.account_seq is None:
                raise ValueError("계좌 API 호출에는 TOSS_ACCOUNT_SEQ가 필요합니다.")
            headers["X-Tossinvest-Account"] = str(self.account_seq)
        request = urllib.request.Request(
            url, data=data, method=method, headers=headers
        )
        payload, _ = self._open(request, authenticated=True, group=group)
        return payload.get("result", payload)

    def accounts(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/accounts", "ACCOUNT")

    def rankings(self, count: int = 30) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            "/api/v1/rankings",
            "RANKING",
            query={
                "type": "MARKET_TRADING_AMOUNT",
                "marketCountry": "KR",
                "duration": "realtime",
                "excludeInvestmentCaution": True,
                "count": count,
            },
        )
        return result.get("rankings", [])

    def candles(self, symbol: str, count: int = 30) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            "/api/v1/candles",
            "MARKET_DATA_CHART",
            query={
                "symbol": symbol,
                "interval": "1m",
                "count": count,
                "adjusted": True,
            },
        )
        return result.get("candles", [])

    def prices(self, symbols: list[str]) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/api/v1/prices",
            "MARKET_DATA",
            query={"symbols": ",".join(symbols)},
        )

    def orderbook(self, symbol: str) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/v1/orderbook",
            "MARKET_DATA",
            query={"symbol": symbol},
        )

    def stock_warnings(self, symbol: str) -> list[dict[str, Any]]:
        return self._request(
            "GET", f"/api/v1/stocks/{symbol}/warnings", "STOCK"
        )

    def kr_market_calendar(self) -> dict[str, Any]:
        return self._request(
            "GET", "/api/v1/market-calendar/KR", "MARKET_INFO"
        )

    def holdings(self) -> dict[str, Any]:
        return self._request(
            "GET", "/api/v1/holdings", "ASSET", account=True
        )

    def buying_power(self) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/v1/buying-power",
            "ORDER_INFO",
            query={"currency": "KRW"},
            account=True,
        )

    def price_limits(self, symbol: str) -> dict[str, Any]:
        return self._request(
            "GET", "/api/v1/price-limits", "MARKET_DATA", query={"symbol": symbol}
        )

    def pending_orders(self) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            "/api/v1/orders",
            "ORDER_HISTORY",
            query={"status": "OPEN"},
            account=True,
        )
        if isinstance(result, list):
            return result
        return result.get("orders", result.get("pendingOrders", []))

    def create_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: int,
        client_order_id: str,
        order_type: str = "MARKET",
        price: Decimal | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "clientOrderId": client_order_id,
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "quantity": str(quantity),
        }
        if order_type == "LIMIT":
            if price is None or price <= 0:
                raise ValueError("LIMIT 주문에는 양수 price가 필요합니다.")
            body["price"] = format(price, "f")
        return self._request(
            "POST",
            "/api/v1/orders",
            "ORDER",
            body=body,
            account=True,
        )

    def create_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: int,
        client_order_id: str,
    ) -> dict[str, Any]:
        return self.create_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            client_order_id=client_order_id,
        )

    def order(self, order_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/v1/orders/{urllib.parse.quote(order_id, safe='')}",
            "ORDER_HISTORY",
            account=True,
        )

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/orders/{urllib.parse.quote(order_id, safe='')}/cancel",
            "ORDER",
            body={},
            account=True,
        )
