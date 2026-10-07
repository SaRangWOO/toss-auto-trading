from __future__ import annotations

import csv
import json
import tempfile
import unittest
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from toss_trader.kis_data import (
    FLOW_FIELDS,
    MINUTE_FIELDS,
    KisDataSettings,
    KisResearchClient,
    merge_csv_rows,
    normalize_kis_flow_rows,
)


class KisDataTests(unittest.TestCase):
    def settings(self, root: Path) -> KisDataSettings:
        return KisDataSettings(
            enabled=True,
            app_key="test-app-key",
            app_secret="test-app-secret",
            base_url="https://example.test",
            request_interval_seconds=0,
            project_root=root,
        )

    def test_minute_collection_is_read_only_and_normalized(self) -> None:
        calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

        def transport(method, url, headers, body, timeout):
            calls.append((method, url, headers, body))
            if url.endswith("/oauth2/tokenP"):
                request = json.loads((body or b"").decode("utf-8"))
                self.assertEqual(request["appkey"], "test-app-key")
                return {"access_token": "fake-access-token"}
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            self.assertEqual(query["FID_INPUT_ISCD"], ["005930"])
            return {
                "rt_cd": "0",
                "output2": [
                    {
                        "stck_bsop_date": "20260824",
                        "stck_cntg_hour": "090000",
                        "stck_oprc": "100",
                        "stck_hgpr": "103",
                        "stck_lwpr": "99",
                        "stck_prpr": "102",
                        "cntg_vol": "1,000",
                        "acml_tr_pbmn": "102000",
                    },
                    {
                        "stck_bsop_date": "20260823",
                        "stck_cntg_hour": "153000",
                        "stck_oprc": "90",
                        "stck_hgpr": "90",
                        "stck_lwpr": "90",
                        "stck_prpr": "90",
                        "cntg_vol": "1",
                        "acml_tr_pbmn": "90",
                    },
                ],
            }

        with tempfile.TemporaryDirectory() as temporary:
            client = KisResearchClient(
                self.settings(Path(temporary)), transport=transport
            )
            bars = client.minute_bars("005930", date(2026, 8, 24))

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["timestamp"], "2026-08-24T09:00:00+09:00")
        self.assertEqual(bars[0]["volume"], "1000")
        self.assertTrue(all(method in {"GET", "POST"} for method, *_ in calls))
        self.assertTrue(all("/trading/" not in url for _, url, *_ in calls))
        data_call = next(call for call in calls if call[0] == "GET")
        self.assertEqual(data_call[2]["tr_id"], "FHKST03010230")

    def test_flow_rows_use_observation_time_when_api_has_no_clock(self) -> None:
        observed = datetime(2026, 8, 25, 10, 5, tzinfo=timezone(timedelta(hours=9)))
        rows = normalize_kis_flow_rows(
            "005930",
            [{"orgn_ntby_qty": "100", "frgn_ntby_qty": "50"}],
            observed,
        )
        self.assertEqual(rows[0]["timestamp"], observed.isoformat())
        self.assertEqual(rows[0]["institution_net_buy"], "100")
        self.assertEqual(rows[0]["foreign_net_buy"], "50")

    def test_csv_merge_is_atomic_and_deduplicates_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "minute.csv"
            first = {
                field: "" for field in MINUTE_FIELDS
            }
            first.update(
                {
                    "timestamp": "2026-08-24T09:00:00+09:00",
                    "symbol": "005930",
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100",
                    "volume": "10",
                    "trading_amount": "1000",
                    "source": "kis",
                }
            )
            self.assertEqual(
                merge_csv_rows(
                    path,
                    [first],
                    fields=MINUTE_FIELDS,
                    key_fields=("timestamp", "symbol"),
                ),
                1,
            )
            updated = dict(first, close="102")
            self.assertEqual(
                merge_csv_rows(
                    path,
                    [updated],
                    fields=MINUTE_FIELDS,
                    key_fields=("timestamp", "symbol"),
                ),
                0,
            )
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["close"], "102")
            self.assertFalse(path.with_suffix(".csv.tmp").exists())

    def test_flow_schema_does_not_contain_credentials(self) -> None:
        self.assertNotIn("app_key", FLOW_FIELDS)
        self.assertNotIn("app_secret", FLOW_FIELDS)


if __name__ == "__main__":
    unittest.main()
