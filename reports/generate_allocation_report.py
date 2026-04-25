#!/usr/bin/env python3
"""Capital Allocation レポートを生成する CLI。"""

from __future__ import annotations

import logging
import sys
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reports.capital_allocation import build_allocation_report, format_allocation_markdown
from reports.department_classifier import load_department_profiles
from reports.ebay_data_fetcher import fetch_completed_orders
from reports.intelligence import build_department_summary, build_tag_rankings, month_label_from_date
from reports.market_signals import build_market_signals
from reports.report_generator import month_range_tokyo

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("allocation_report")


def main() -> None:
    start_local, end_local = month_range_tokyo()
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    profiles = load_department_profiles(ROOT / "sourcing")
    logger.info("GetOrders 取得: %s 〜 %s (UTC)", start_utc.isoformat(), end_utc.isoformat())
    sold_lines = fetch_completed_orders(start_utc, end_utc)
    logger.info("取得件数: %s 取引行", len(sold_lines))

    dept_rows = build_department_summary(sold_lines, profiles)
    tag_rankings = build_tag_rankings(sold_lines)
    market = build_market_signals(today=end_local.date())
    report = build_allocation_report(
        dept_rows,
        tag_rankings=tag_rankings,
        market=market,
        month_label=month_label_from_date(start_local),
    )
    body = format_allocation_markdown(report)
    print(body)

    out_path = ROOT / "reports" / "output" / f"allocation_{start_local.year:04d}-{start_local.month:02d}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    print(f"レポート保存: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
