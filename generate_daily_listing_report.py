#!/usr/bin/env python3
"""logs/daily_report_YYYY-MM-DD.md を生成する（JST）。cron で 0 時以降に回す想定。

例:
  python3 generate_daily_listing_report.py
  python3 generate_daily_listing_report.py --date 2026-04-09
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from listing_metrics import write_daily_report_md  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(
        description="出品日報 Markdown を logs / knowledge_vault に出力し、任意で Obsidian で開く"
    )
    p.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="JST の日付（省略時は今日）",
    )
    p.add_argument(
        "--open",
        action="store_true",
        help="macOS 等で Obsidian を起動し、当日の「日報/出品_日付.md」を開く",
    )
    p.add_argument(
        "--open-dashboard",
        action="store_true",
        help="Vault ルートの 00_ダッシュボード.md を開く",
    )
    p.add_argument(
        "--open-daily",
        action="store_true",
        help="obsidian://daily（デイリーノートを開く／作成。コアのデイリーノート要）",
    )
    p.add_argument(
        "--search",
        metavar="QUERY",
        nargs="?",
        const="",
        default=None,
        help="obsidian://search（QUERY 省略時は検索パネルのみ）",
    )
    args = p.parse_args()
    path, obs = write_daily_report_md(args.date)
    print(path)
    if obs:
        print(obs)

    from datetime import datetime, timedelta, timezone

    JST = timezone(timedelta(hours=9))
    if args.date:
        day = args.date
    else:
        day = datetime.now(JST).strftime("%Y-%m-%d")

    if args.open or args.open_dashboard or args.open_daily or args.search is not None:
        from obsidian_uri import (  # noqa: E402
            open_daily_note,
            open_file_in_vault,
            open_search,
        )

    if args.open_dashboard:
        ok = open_file_in_vault("00_ダッシュボード.md")
        print("obsidian://open 00_ダッシュボード.md", "ok" if ok else "失敗（Vault 未登録の可能性）")
    if args.open:
        rel = f"日報/出品_{day}.md"
        ok = open_file_in_vault(rel)
        print(f"obsidian://open {rel}", "ok" if ok else "失敗（Vault 未登録の可能性）")
    if args.open_daily:
        ok = open_daily_note()
        print("obsidian://daily", "ok" if ok else "失敗")
    if args.search is not None:
        ok = open_search(query=args.search if args.search != "" else None)
        print("obsidian://search", "ok" if ok else "失敗")


if __name__ == "__main__":
    main()
