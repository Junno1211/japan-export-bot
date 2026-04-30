"""inventory v3: active_dual_reject と detail CSV の MAINTAINED_DUAL_REJECT 行の整合。"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from v3_dual_reject_invariant import assert_dual_reject_detail_matches_counts  # noqa: E402


def test_dual_reject_count_matches_maintained_dual_reject_rows() -> None:
    counts = {"active_dual_reject": 2}
    rows = [
        {"action_taken": "MAINTAINED_DUAL_REJECT"},
        {"action_taken": "MAINTAINED"},
        {"action_taken": "MAINTAINED_DUAL_REJECT"},
    ]
    assert_dual_reject_detail_matches_counts(counts, rows)


def test_dual_reject_mismatch_raises() -> None:
    counts = {"active_dual_reject": 1}
    rows = [
        {"action_taken": "MAINTAINED_DUAL_REJECT"},
        {"action_taken": "MAINTAINED_DUAL_REJECT"},
    ]
    with pytest.raises(AssertionError) as exc:
        assert_dual_reject_detail_matches_counts(counts, rows)
    assert "active_dual_reject=1" in str(exc.value)
