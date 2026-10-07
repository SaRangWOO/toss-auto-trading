from __future__ import annotations

import json
import os
import time
import csv
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, time as clock_time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import load_dotenv


KST = timezone(timedelta(hours=9))
JsonTransport = Callable[
    [str, str, dict[str, str], bytes | None, float], dict[str, Any]
]


class KisDataError(RuntimeError):
    """Raised when the read-only KIS research API cannot return valid data."""


def _urllib_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", errors="replace"))
            code = detail.get("msg_cd") or detail.get("error_code") or "http_error"
        except (ValueError, AttributeError):
            code = "http_error"
        raise KisDataError(f"KIS HTTP error status={exc.code} code={code}") from exc
    except urllib.error.URLError as exc:
        raise KisDataError(f"KIS network error: {type(exc.reason).__name__}") from exc
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KisDataError("KIS returned an invalid JSON response") from exc
    if not isinstance(parsed, dict):
        raise KisDataError("KIS returned a non-object JSON response")
    return parsed


@dataclass(frozen=True)
class KisDataSettings:
    enabled: bool
    app_key: str
    app_secret: str
    base_url: str
    request_interval_seconds: float
    project_root: Path

    @classmethod
    def from_project(cls, project_root: Path) -> "KisDataSettings":
        root = project_root.resolve()
        load_dotenv(root / ".env")
        enabled = os.getenv("KIS_DATA_ENABLED", "false").strip().lower()
        if enabled not in {"true", "false"}:
            raise ValueError("KIS_DATA_ENABLED must be true or false")
        settings = cls(
            enabled=enabled == "true",
            app_key=os.getenv("KIS_APP_KEY", "").strip(),
            app_secret=os.getenv("KIS_APP_SECRET", "").strip(),
            base_url=os.getenv(
                "KIS_BASE_URL", "https://openapi.koreainvestment.com:9443"
            ).strip().rstrip("/"),
            request_interval_seconds=float(
                os.getenv("KIS_REQUEST_INTERVAL_SECONDS", "0.20")
            ),
            project_root=root,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.enabled:
            raise ValueError(
                "KIS research data is disabled. Set KIS_DATA_ENABLED=true locally."
            )
        if not self.app_key or not self.app_secret:
            raise ValueError("KIS_APP_KEY and KIS_APP_SECRET are required")
        if not self.base_url.startswith("https://"):
            raise ValueError("KIS_BASE_URL must use HTTPS")
        if not 0 <= self.request_interval_seconds <= 10:
            raise ValueError("KIS_REQUEST_INTERVAL_SECONDS must be between 0 and 10")


class KisResearchClient:
    """Small read-only client for official KIS historical and flow endpoints."""

    def __init__(
        self,
        settings: KisDataSettings,
        *,
        transport: JsonTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.settings = settings
        self.transport = transport or _urllib_transport
        self.timeout = timeout
        self.access_token: str | None = None
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        interval = self.settings.request_interval_seconds
        remaining = interval - (time.monotonic() - self._last_request_at)
        if remaining > 0:
            time.sleep(remaining)

    def issue_token(self) -> str:
        body = json.dumps(
            {
                "grant_type": "client_credentials",
                "appkey": self.settings.app_key,
                "appsecret": self.settings.app_secret,
            }
        ).encode("utf-8")
        payload = self.transport(
            "POST",
            f"{self.settings.base_url}/oauth2/tokenP",
            {"Content-Type": "application/json"},
            body,
            self.timeout,
        )
        token = str(payload.get("access_token", "")).strip()
        if not token:
            code = payload.get("error_code") or payload.get("msg_cd") or "unknown"
            raise KisDataError(f"KIS token issuance failed code={code}")
        self.access_token = token
        return token

    def _get(
        self,
        path: str,
        tr_id: str,
        params: dict[str, str],
    ) -> dict[str, Any]:
        if self.access_token is None:
            self.issue_token()
        assert self.access_token is not None
        self._throttle()
        query = urllib.parse.urlencode(params)
        payload = self.transport(
            "GET",
            f"{self.settings.base_url}{path}?{query}",
            {
                "Content-Type": "application/json",
                "authorization": f"Bearer {self.access_token}",
                "appkey": self.settings.app_key,
                "appsecret": self.settings.app_secret,
                "tr_id": tr_id,
            },
            None,
            self.timeout,
        )
        self._last_request_at = time.monotonic()
        if str(payload.get("rt_cd", "0")) != "0":
            code = payload.get("msg_cd") or "unknown"
            raise KisDataError(f"KIS data request failed code={code}")
        return payload

    def minute_bars_page(
        self,
        symbol: str,
        trading_day: date,
        before_time: clock_time = clock_time(15, 30),
    ) -> list[dict[str, Any]]:
        if len(symbol) != 6 or not symbol.isalnum():
            raise ValueError("KIS symbol must be a six-character stock code")
        payload = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice",
            "FHKST03010230",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_HOUR_1": before_time.strftime("%H%M%S"),
                "FID_INPUT_DATE_1": trading_day.strftime("%Y%m%d"),
                "FID_PW_DATA_INCU_YN": "N",
                "FID_FAKE_TICK_INCU_YN": "",
            },
        )
        rows = payload.get("output2", [])
        if not isinstance(rows, list):
            raise KisDataError("KIS minute response output2 is not a list")
        return [row for row in rows if isinstance(row, dict)]

    def minute_bars(self, symbol: str, trading_day: date) -> list[dict[str, str]]:
        """Fetch one regular session without crossing into another trading day."""
        before = clock_time(15, 30)
        collected: dict[str, dict[str, str]] = {}
        for _ in range(5):
            page = self.minute_bars_page(symbol, trading_day, before)
            normalized = normalize_kis_minute_rows(symbol, page, trading_day)
            if not normalized:
                break
            for row in normalized:
                collected[row["timestamp"]] = row
            earliest = min(datetime.fromisoformat(row["timestamp"]) for row in normalized)
            if earliest.time() <= clock_time(9, 0):
                break
            previous = earliest - timedelta(minutes=1)
            next_before = previous.time().replace(second=0, microsecond=0)
            if next_before >= before:
                break
            before = next_before
        return [collected[key] for key in sorted(collected)]

    def investor_trend(self, symbol: str) -> list[dict[str, Any]]:
        if len(symbol) != 6 or not symbol.isalnum():
            raise ValueError("KIS symbol must be a six-character stock code")
        payload = self._get(
            "/uapi/domestic-stock/v1/quotations/investor-trend-estimate",
            "HHPTJ04160200",
            {"MKSC_SHRN_ISCD": symbol},
        )
        rows = payload.get("output2", [])
        if not isinstance(rows, list):
            raise KisDataError("KIS investor response output2 is not a list")
        return [row for row in rows if isinstance(row, dict)]


def _number(value: Any) -> str:
    text = str(value or "0").strip().replace(",", "")
    try:
        return str(Decimal(text))
    except Exception as exc:
        raise KisDataError("KIS numeric field could not be normalized") from exc


def normalize_kis_minute_rows(
    symbol: str,
    rows: Iterable[dict[str, Any]],
    expected_day: date,
) -> list[dict[str, str]]:
    normalized: dict[str, dict[str, str]] = {}
    for row in rows:
        day_text = str(row.get("stck_bsop_date", "")).strip()
        time_text = str(row.get("stck_cntg_hour", "")).strip().zfill(6)
        if day_text != expected_day.strftime("%Y%m%d") or len(time_text) != 6:
            continue
        try:
            timestamp = datetime.strptime(
                day_text + time_text, "%Y%m%d%H%M%S"
            ).replace(tzinfo=KST)
        except ValueError:
            continue
        if not clock_time(9, 0) <= timestamp.time() <= clock_time(15, 30):
            continue
        item = {
            "timestamp": timestamp.isoformat(),
            "symbol": symbol,
            "open": _number(row.get("stck_oprc")),
            "high": _number(row.get("stck_hgpr")),
            "low": _number(row.get("stck_lwpr")),
            "close": _number(row.get("stck_prpr")),
            "volume": _number(row.get("cntg_vol")),
            "trading_amount": _number(row.get("acml_tr_pbmn")),
            "source": "kis",
        }
        normalized[item["timestamp"]] = item
    return [normalized[key] for key in sorted(normalized)]


def normalize_kis_flow_rows(
    symbol: str,
    rows: Iterable[dict[str, Any]],
    observed_at: datetime,
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for row in rows:
        time_text = str(
            row.get("bsop_hour")
            or row.get("stck_cntg_hour")
            or row.get("data_rank")
            or ""
        ).strip()
        timestamp = observed_at
        if len(time_text) >= 4 and time_text[:4].isdigit():
            try:
                timestamp = observed_at.replace(
                    hour=int(time_text[:2]),
                    minute=int(time_text[2:4]),
                    second=int(time_text[4:6]) if len(time_text) >= 6 else 0,
                    microsecond=0,
                )
            except ValueError:
                timestamp = observed_at
        normalized.append(
            {
                "timestamp": timestamp.isoformat(),
                "symbol": symbol,
                "institution_net_buy": _number(
                    row.get("orgn_ntby_qty") or row.get("orgn_ntby_tr_pbmn")
                ),
                "foreign_net_buy": _number(
                    row.get("frgn_ntby_qty") or row.get("frgn_ntby_tr_pbmn")
                ),
                "program_net_buy": _number(
                    row.get("all_ntby_qty") or row.get("all_ntby_amt")
                ),
                "source": "kis_investor_trend_estimate",
            }
        )
    return normalized


MINUTE_FIELDS = (
    "timestamp",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trading_amount",
    "source",
)

FLOW_FIELDS = (
    "timestamp",
    "symbol",
    "institution_net_buy",
    "foreign_net_buy",
    "program_net_buy",
    "source",
)


def merge_csv_rows(
    path: Path,
    rows: Iterable[dict[str, Any]],
    *,
    fields: tuple[str, ...],
    key_fields: tuple[str, ...],
) -> int:
    """Atomically merge normalized research rows without duplicating keys."""
    merged: dict[tuple[str, ...], dict[str, str]] = {}
    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != fields:
                raise ValueError(f"existing CSV schema does not match: {path}")
            for row in reader:
                key = tuple(row.get(field, "") for field in key_fields)
                merged[key] = {field: row.get(field, "") for field in fields}
    before = len(merged)
    for row in rows:
        normalized = {field: str(row.get(field, "")) for field in fields}
        key = tuple(normalized[field] for field in key_fields)
        if any(not value for value in key):
            raise ValueError("research CSV row has an empty key")
        merged[key] = normalized
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(merged[key] for key in sorted(merged))
    temporary.replace(path)
    return len(merged) - before
