#!/usr/bin/env python3
"""
items.csv の ebay_item_id を対象に、eBay で「アクティブかつ在庫数量0」の出品だけ EndFixedPriceItem で終了する。

Seller Hub に残った在庫0・非表示の出品を掃除してやり直す用途。

  cd 海外輸出ボット
  python3 scripts/end_oos_listings_from_csv.py --dry-run
  python3 scripts/end_oos_listings_from_csv.py
  python3 scripts/end_oos_listings_from_csv.py --limit 20

--force-end-all: GetItem を飛ばし csv の ID をすべて終了（危険・在庫ありも終了しうる）
"""
from __future__ import annotations

import argparse
import csv
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
logger = logging.getLogger("end_oos")


# quantity は 0 が有効値のため `int(x.get("quantity", -1) or -1)` は禁止（0 or -1 → -1）。
def _parse_quantity(r: dict, key: str = "quantity") -> int:
    v = r.get(key)
    if v is None:
        return -1
    try:
        return int(v)
    except (TypeError, ValueError):
        return -1


def main() -> int:
    parser = argparse.ArgumentParser(description="在庫0の固定価格出品を終了（items.csv）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--force-end-all",
        action="store_true",
        help="在庫数を確認せず csv の全 ItemID を終了（要注意）",
    )
    args = parser.parse_args()

    from config import ITEMS_CSV_PATH
    from ebay_updater import end_fixed_price_listing, get_item_status

    csv_path = (
        ITEMS_CSV_PATH
        if os.path.isabs(ITEMS_CSV_PATH)
        else os.path.join(ROOT, ITEMS_CSV_PATH.lstrip("./"))
    )
    if not os.path.isfile(csv_path):
        logger.error("items.csv がありません: %s", csv_path)
        return 1

    ids: list[str] = []
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            eid = (row.get("ebay_item_id") or "").strip()
            if eid:
                ids.append(eid)
    # 重複除去（順序維持）
    seen: set[str] = set()
    unique_ids: list[str] = []
    for eid in ids:
        if eid not in seen:
            seen.add(eid)
            unique_ids.append(eid)

    logger.info("items.csv から ItemID: %s 件（ユニーク）", len(unique_ids))

    ended = 0
    skipped = 0
    failed = 0
    n = 0

    for ebay_id in unique_ids:
        if args.limit and n >= args.limit:
            break
        n += 1

        if args.force_end_all:
            if args.dry_run:
                logger.info("[dry-run] force end %s", ebay_id)
                continue
            r = end_fixed_price_listing(ebay_id)
            if r.get("success"):
                ended += 1
            else:
                failed += 1
            time.sleep(0.35)
            continue

        if args.dry_run:
            gst = get_item_status(ebay_id)
            qty = _parse_quantity(gst)
            ls = gst.get("listing_status", "")
            logger.info(
                "[dry-run] %s qty=%s status=%s → %s",
                ebay_id,
                qty,
                ls,
                "終了対象" if _is_oos_active(gst) else "スキップ",
            )
            time.sleep(0.2)
            continue

        gst = get_item_status(ebay_id)
        if not gst.get("success"):
            logger.warning("GetItem 失敗スキップ: %s", ebay_id)
            failed += 1
            time.sleep(0.3)
            continue

        if not _is_oos_active(gst):
            skipped += 1
            logger.info(
                "スキップ（在庫0でない or 非アクティブ）: %s qty=%s %s",
                ebay_id,
                gst.get("quantity"),
                gst.get("listing_status"),
            )
            time.sleep(0.15)
            continue

        r = end_fixed_price_listing(ebay_id)
        if r.get("success"):
            ended += 1
        else:
            failed += 1
        time.sleep(0.4)

    logger.info(
        "=== 完了 === 終了=%s スキップ=%s 失敗=%s",
        ended,
        skipped,
        failed,
    )
    return 0 if failed == 0 else 1


def _is_oos_active(gst: dict) -> bool:
    ls = (gst.get("listing_status") or "").strip().lower()
    qty = _parse_quantity(gst)
    if qty != 0:
        return False
    if "active" not in ls:
        return False
    return True


if __name__ == "__main__":
    sys.exit(main())
