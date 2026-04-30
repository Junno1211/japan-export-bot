# -*- coding: utf-8 -*-
"""inventory v3: active_dual_reject と detail CSV の MAINTAINED_DUAL_REJECT 行数の整合（重い import なし）。"""
from __future__ import annotations

from typing import Dict, List


def assert_dual_reject_detail_matches_counts(
    counts: Dict[str, int], detail_rows: List[dict[str, str]]
) -> None:
    n_cnt = int(counts.get("active_dual_reject", 0))
    n_rows = sum(
        1 for r in detail_rows if r.get("action_taken") == "MAINTAINED_DUAL_REJECT"
    )
    if n_cnt != n_rows:
        raise AssertionError(
            f"inventory_v3: active_dual_reject={n_cnt} != "
            f"MAINTAINED_DUAL_REJECT detail rows={n_rows}"
        )
