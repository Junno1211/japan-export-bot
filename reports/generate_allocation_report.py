#!/usr/bin/env python3
"""Capital Allocation レポートを生成する CLI。"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reports.capital_allocation import DepartmentMonthSnapshot, build_allocation_report, format_allocation_markdown, revenue_jpy
from reports.department_classifier import load_department_profiles
from reports.ebay_data_fetcher import fetch_completed_orders
from reports.intelligence import build_department_summary, build_tag_rankings, month_label_from_date
from reports.market_signals import build_market_signals
from reports.report_generator import month_range_tokyo

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("allocation_report")


def _month_key(dt: datetime) -> str:
    return f"{dt.year:04d}-{dt.month:02d}"


def _previous_month_start(dt: datetime) -> datetime:
    tz = dt.tzinfo or ZoneInfo("Asia/Tokyo")
    if dt.month == 1:
        return datetime(dt.year - 1, 12, 1, tzinfo=tz)
    return datetime(dt.year, dt.month - 1, 1, tzinfo=tz)


def _rows_to_snapshots(month: str, rows) -> dict[str, DepartmentMonthSnapshot]:
    return {
        row.department: DepartmentMonthSnapshot(month=month, revenue_jpy=revenue_jpy(row.revenue_usd), count=row.count)
        for row in rows
    }


def fetch_department_history(
    *,
    current_start_local: datetime,
    current_rows,
    profiles,
    months: int = 3,
) -> dict[str, list[DepartmentMonthSnapshot]]:
    """当月を含む直近 N ヶ月の部署別売上スナップショットを作る。"""
    history: dict[str, list[DepartmentMonthSnapshot]] = {}
    for dept, snap in _rows_to_snapshots(_month_key(current_start_local), current_rows).items():
        history.setdefault(dept, []).append(snap)

    cursor = current_start_local
    for _ in range(max(0, months - 1)):
        prev_start = _previous_month_start(cursor)
        prev_end = cursor
        try:
            lines = fetch_completed_orders(prev_start.astimezone(timezone.utc), prev_end.astimezone(timezone.utc))
        except Exception as e:  # noqa: BLE001 - 履歴欠損でも当月レポートは生成する
            logger.warning("履歴取得に失敗: %s (%s)", _month_key(prev_start), e)
            cursor = prev_start
            continue
        rows = build_department_summary(lines, profiles)
        for dept, snap in _rows_to_snapshots(_month_key(prev_start), rows).items():
            history.setdefault(dept, []).append(snap)
        cursor = prev_start
    return history


def main() -> None:
    start_local, end_local = month_range_tokyo()
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    profiles = load_department_profiles(ROOT / "sourcing")
    logger.info("GetOrders 取得: %s 〜 %s (UTC)", start_utc.isoformat(), end_utc.isoformat())
    sold_lines = fetch_completed_orders(start_utc, end_utc)
    logger.info("取得件数: %s 取引行", len(sold_lines))

    dept_rows = build_department_summary(sold_lines, profiles)
    history = fetch_department_history(current_start_local=start_local, current_rows=dept_rows, profiles=profiles)
    tag_rankings = build_tag_rankings(sold_lines)
    market = build_market_signals(today=end_local.date())
    report = build_allocation_report(
        dept_rows,
        tag_rankings=tag_rankings,
        market=market,
        history_by_department=history,
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
