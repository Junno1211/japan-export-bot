#!/usr/bin/env python3
"""Market Signals レポートを生成する CLI。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reports.ebay_data_fetcher import fetch_completed_orders
from reports.market_signals import build_market_signals, format_market_signals_markdown, month_key, previous_month_keys, report_to_dict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("market_signals")


def _month_start(key: str) -> date:
    year_s, month_s = key.split("-", 1)
    return date(int(year_s), int(month_s), 1)


def _next_month_start(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def fetch_monthly_sales_counts(today: date) -> dict[str, int]:
    """当月と過去3ヶ月の販売件数を GetOrders から取得する。失敗月は欠損扱い。"""
    keys = [month_key(today), *previous_month_keys(today, 3)]
    counts: dict[str, int] = {}
    tz = ZoneInfo("Asia/Tokyo")
    for key in keys:
        start_d = _month_start(key)
        end_d = min(_next_month_start(start_d), today + timedelta(days=1))
        start = datetime(start_d.year, start_d.month, start_d.day, tzinfo=tz).astimezone(timezone.utc)
        end = datetime(end_d.year, end_d.month, end_d.day, tzinfo=tz).astimezone(timezone.utc)
        try:
            counts[key] = len(fetch_completed_orders(start, end))
        except Exception as e:  # noqa: BLE001 - レポート生成を止めない
            logger.warning("月次件数取得に失敗: %s (%s)", key, e)
    return counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="為替・季節・トレンドの Market Signals レポートを生成")
    parser.add_argument("--json", action="store_true", help="JSON ファイルも出力する")
    args = parser.parse_args(argv)

    today = date.today()
    monthly_counts = fetch_monthly_sales_counts(today)
    report = build_market_signals(today=today, monthly_counts=monthly_counts)
    body = format_market_signals_markdown(report)
    print(body)

    out_dir = ROOT / "reports" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"market_signals_{today.isoformat()}.md"
    md_path.write_text(body, encoding="utf-8")
    print(f"Markdown 保存: {md_path.relative_to(ROOT)}")

    if args.json:
        json_path = out_dir / f"market_signals_{today.isoformat()}.json"
        json_path.write_text(
            json.dumps(report_to_dict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"JSON 保存: {json_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
