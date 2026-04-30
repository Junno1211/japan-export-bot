#!/usr/bin/env python3
"""
アカウントの ActiveList（Seller Hub のアクティブ出品）から、在庫数量0の出品だけ EndFixedPriceItem で終了する。
items.csv が古く GetItem が Completed になっている ID とは別に、いま本当に Active な OOS を掃除する。

  cd 海外輸出ボット
  python3 scripts/end_active_zero_qty_listings.py --dry-run
  python3 scripts/end_active_zero_qty_listings.py
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("end_active_zero")


def main() -> int:
    parser = argparse.ArgumentParser(description="ActiveList の在庫0出品を終了")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    from ebay_updater import end_fixed_price_listing, get_all_active_list_items

    rows = get_all_active_list_items()
    logger.info("ActiveList 取得: %s 行", len(rows))

    zero = [r for r in rows if r.get("quantity") == 0]
    logger.info("在庫数量0: %s 件", len(zero))

    ended = 0
    failed = 0
    n = 0
    for r in zero:
        if args.limit and n >= args.limit:
            break
        n += 1
        iid = r["item_id"]
        if args.dry_run:
            logger.info("[dry-run] end %s sku=%s", iid, (r.get("sku") or "")[:40])
            continue
        res = end_fixed_price_listing(iid)
        if res.get("success"):
            ended += 1
        else:
            failed += 1
        time.sleep(0.45)

    logger.info("=== 完了 === 終了試行=%s 成功=%s 失敗=%s", n, ended, failed)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
