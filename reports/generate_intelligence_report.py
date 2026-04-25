#!/usr/bin/env python3
"""Intelligence レポートを生成する CLI。"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reports.department_classifier import load_department_profiles
from reports.ebay_data_fetcher import fetch_completed_orders
from reports.intelligence import (
    build_intelligence_report,
    format_intelligence_markdown,
    month_label_from_date,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("intelligence_report")


def parse_month_arg(value: str | None) -> tuple[datetime, datetime]:
    tz = ZoneInfo("Asia/Tokyo")
    if value:
        try:
            year_s, month_s = value.split("-", 1)
            year = int(year_s)
            month = int(month_s)
            if not 1 <= month <= 12:
                raise ValueError
        except ValueError:
            raise SystemExit("--month は YYYY-MM 形式で指定してください") from None
        start = datetime(year, month, 1, tzinfo=tz)
    else:
        now = datetime.now(tz)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    if start.month == 12:
        end = datetime(start.year + 1, 1, 1, tzinfo=tz)
    else:
        end = datetime(start.year, start.month + 1, 1, tzinfo=tz)
    return start, end


def previous_month_range(start: datetime) -> tuple[datetime, datetime]:
    tz = start.tzinfo or ZoneInfo("Asia/Tokyo")
    if start.month == 1:
        prev_start = datetime(start.year - 1, 12, 1, tzinfo=tz)
    else:
        prev_start = datetime(start.year, start.month - 1, 1, tzinfo=tz)
    return prev_start, start


def fetch_lines_for_range(start_local: datetime, end_local: datetime):
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    logger.info("GetOrders 取得: %s 〜 %s (UTC)", start_utc.isoformat(), end_utc.isoformat())
    lines = fetch_completed_orders(start_utc, end_utc)
    logger.info("取得件数: %s 取引行", len(lines))
    return lines


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="売れ筋パターンを抽出する Intelligence レポートを生成")
    parser.add_argument("--month", metavar="YYYY-MM", help="対象月（未指定時は当月）")
    parser.add_argument("--compare-prev", action="store_true", help="前月データと比較する")
    args = parser.parse_args(argv)

    start_local, end_local = parse_month_arg(args.month)
    profiles = load_department_profiles(ROOT / "sourcing")
    if not profiles:
        logger.warning("sourcing/*/keywords.json が見つかりません（未分類のみになります）")

    current_lines = fetch_lines_for_range(start_local, end_local)
    previous_lines = None
    if args.compare_prev:
        prev_start, prev_end = previous_month_range(start_local)
        previous_lines = fetch_lines_for_range(prev_start, prev_end)

    report = build_intelligence_report(
        current_lines,
        profiles,
        month_label=month_label_from_date(start_local),
        previous_sold_lines=previous_lines,
    )
    body = format_intelligence_markdown(report)
    print(body)

    out_path = ROOT / "reports" / "output" / f"intelligence_{start_local.year:04d}-{start_local.month:02d}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    print(f"レポート保存: {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
