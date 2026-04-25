#!/usr/bin/env python3
"""
部署別売上レポート（当月・Asia/Tokyo）。

標準出力に表を表示し、`reports/output/dept_report_<YYYY-MM>.md` に保存する。
認証は `import config` のみ（config.py は変更しない）。
"""

from __future__ import annotations

import logging
import sys
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 常に先頭へ（`python3 reports/generate_dept_report.py` でも config を解決できるようにする）
sys.path.insert(0, str(ROOT))

from reports.department_classifier import load_department_profiles
from reports.ebay_data_fetcher import fetch_completed_orders
from reports.report_generator import (
    aggregate_sales_by_department,
    build_total_row,
    format_terminal_table,
    month_range_tokyo,
    try_load_item_cost_jpy,
    write_markdown_report,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dept_report")


def main() -> None:
    start_local, end_local = month_range_tokyo()
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    profiles = load_department_profiles(ROOT / "sourcing")
    if not profiles:
        logger.warning("sourcing/*/keywords.json が見つかりません（未分類のみになります）")

    logger.info("GetOrders 取得: %s 〜 %s (UTC)", start_utc.isoformat(), end_utc.isoformat())
    lines = fetch_completed_orders(start_utc, end_utc)
    logger.info("取得件数: %s 取引行", len(lines))

    cost = try_load_item_cost_jpy(ROOT)
    rows, meta = aggregate_sales_by_department(lines, profiles, cost)
    total = build_total_row(rows)

    y, m = start_local.year, start_local.month
    d0, d1 = start_local.day, end_local.day
    date_from = start_local.strftime("%Y-%m-%d")
    date_to = end_local.strftime("%Y-%m-%d %H:%M")

    text = format_terminal_table(y, m, d0, d1, rows, total_row=total)
    print(text)
    out_path = ROOT / "reports" / "output" / f"dept_report_{y:04d}-{m:02d}.md"
    write_markdown_report(
        out_path,
        y,
        m,
        date_from,
        date_to,
        rows,
        total,
        unclassified_count=int(meta["unclassified_count"]),
        profits_enabled=bool(meta["profits_enabled"]),
    )
    print(f"レポート保存: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
