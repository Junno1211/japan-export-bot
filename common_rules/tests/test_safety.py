"""common_rules.safety の単体テスト。"""

from __future__ import annotations

import pytest

from common_rules.safety import MAX_CANCELLATION_RATE, is_cancellation_rate_safe


class TestMaxCancellationRate:
    def test_value(self) -> None:
        assert MAX_CANCELLATION_RATE == 0.05


class TestIsCancellationRateSafe:
    @pytest.mark.parametrize(
        "rate,expected",
        [
            (0.0, True),
            (0.03, True),
            (0.05, False),
            (0.06, False),
        ],
    )
    def test_thresholds(self, rate: float, expected: bool) -> None:
        assert is_cancellation_rate_safe(rate) is expected

    def test_negative_not_safe(self) -> None:
        assert is_cancellation_rate_safe(-0.01) is False
