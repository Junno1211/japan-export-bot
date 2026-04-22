import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.phase0_guards import (  # noqa: E402
    MercariPipelineStopped,
    verify_independent,
    with_retry,
)
from utils import phase0_guards as pg  # noqa: E402


class TestPhase0Guards(unittest.TestCase):
    def test_verify_independent(self):
        self.assertTrue(verify_independent("sold_out", "sold_out"))
        self.assertFalse(verify_independent("sold_out", "active"))

    def test_with_retry_succeeds_second(self):
        n = {"i": 0}

        def flaky():
            n["i"] += 1
            if n["i"] < 2:
                raise TimeoutError("x")
            return "ok"

        self.assertEqual(with_retry(flaky, retries=1, backoff=0.01), "ok")

    def test_with_retry_exhausted(self):
        def always_fail():
            raise ValueError("no")

        with self.assertRaises(ValueError):
            with_retry(always_fail, retries=1, backoff=0.01)

    def test_rate_limit_guard_429_raises(self):
        resp = MagicMock()
        resp.status_code = 429
        with patch("notifier.notify_slack", lambda *_a, **_k: None):
            with self.assertRaises(RuntimeError):
                pg.rate_limit_guard(resp, "UnitTest")

    def test_rate_limit_guard_non_429(self):
        resp = MagicMock()
        resp.status_code = 200
        pg.rate_limit_guard(resp, "UnitTest")  # no-op

    def test_mercari_pipeline_stopped_is_exception(self):
        with self.assertRaises(MercariPipelineStopped):
            raise MercariPipelineStopped("rl")


if __name__ == "__main__":
    unittest.main()
