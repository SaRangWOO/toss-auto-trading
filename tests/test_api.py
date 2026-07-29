from __future__ import annotations

import gzip
import unittest

from toss_trader.api import TossClient


class ApiTests(unittest.TestCase):
    def test_gzip_error_body_is_decoded(self) -> None:
        payload = (
            '{"error":{"code":"prerequisite-required",'
            '"message":"주문 전 필요한 사전 자격 요건이 충족되지 않았습니다."}}'
        ).encode("utf-8")
        decoded = TossClient._decode_body(gzip.compress(payload), "gzip")
        self.assertIn("prerequisite-required", decoded)
        self.assertIn("사전 자격", decoded)

    def test_gzip_magic_is_detected_without_header(self) -> None:
        payload = b'{"result":{"ok":true}}'
        self.assertEqual(
            TossClient._decode_body(gzip.compress(payload), None),
            payload.decode("utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
