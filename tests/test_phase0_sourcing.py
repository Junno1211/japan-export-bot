"""Phase 0 sourcing まわりの単体テスト（ネットワークなし）。"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestPhase0Sourcing(unittest.TestCase):
    def test_playwright_goto_retry_import(self):
        from utils.phase0_guards import playwright_goto_with_retry

        self.assertTrue(callable(playwright_goto_with_retry))

    @patch("mercari_checker._requests_get")
    def test_mercari_api_snapshot_404(self, m_get):
        m_resp = MagicMock()
        m_resp.status_code = 404
        m_get.return_value = m_resp
        from mercari_checker import _mercari_api_item_snapshot_no_html

        r = _mercari_api_item_snapshot_no_html("m123")
        self.assertEqual(r["status"], "deleted")


if __name__ == "__main__":
    unittest.main()
