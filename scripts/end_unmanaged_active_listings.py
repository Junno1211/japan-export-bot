#!/usr/bin/env python3
"""
ActiveList のうち、無在庫照合不能な出品を EndFixedPriceItem で終了する。

条件（すべて満たすものが対象）:
- eBay SKU にメルカリURLがない（inventory_manager と同じ判定）
- かつ在庫管理表で A列に Item ID がない、または D列にメルカリURLがない

--exclude-item-ids で除外する Item ID を追加できる（デフォルトで4件を除外）。

  cd 海外輸出ボット
  python3 scripts/end_unmanaged_active_listings.py --dry-run
  python3 scripts/end_unmanaged_active_listings.py
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LOG_DIR = os.path.join(ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
_log_path = os.path.join(LOG_DIR, f"end_unmanaged_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_log_path, encoding="utf-8"),
    ],
)
logger = logging.getLogger("end_unmanaged")

DEFAULT_EXCLUDE_ITEM_IDS = frozenset(
    {
        "366329981210",
        "366329844694",
        "366329850427",
        "366326204998",
    }
)


def _mercari_url_from_sku(sku: str) -> str:
    s = (sku or "").strip()
    if not s:
        return ""
    if "mercari" in s.lower() and (s.startswith("http://") or s.startswith("https://")):
        return s
    return ""


def _should_end(
    ebay_item_id: str,
    sku: str,
    sheet_map: dict,
    exclude: set[str],
) -> bool:
    eid = (ebay_item_id or "").strip()
    if not eid:
        return False
    if eid in exclude:
        return False
    if _mercari_url_from_sku(sku):
        return False
    info = sheet_map.get(eid)
    if not info:
        return True
    d = (info.get("mercari_url") or "").strip()
    if d and "mercari" in d.lower():
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="照合不能なアクティブ出品を終了")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--exclude-item-ids",
        default="",
        help="カンマ区切りで追加除外 Item ID（デフォルト4件に加算）",
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    exclude = set(DEFAULT_EXCLUDE_ITEM_IDS)
    if args.exclude_item_ids.strip():
        for part in args.exclude_item_ids.split(","):
            p = part.strip()
            if p:
                exclude.add(p)

    from config import SHEET_NAME
    from ebay_updater import end_fixed_price_listing, get_all_active_list_items
    from sheets_manager import map_ebay_item_id_to_row_and_url

    sheet_map = map_ebay_item_id_to_row_and_url(SHEET_NAME)
    active_list = get_all_active_list_items()
    seen: set[str] = set()
    targets: list[dict] = []

    for r in active_list:
        eid = (r.get("item_id") or "").strip()
        if not eid or eid in seen:
            continue
        seen.add(eid)
        sku = (r.get("sku") or "").strip()
        if not _should_end(eid, sku, sheet_map, exclude):
            continue
        targets.append({"item_id": eid, "sku": sku})

    logger.info("ログ: %s", _log_path)
    logger.info(
        "対象: %s 件（除外 %s 件は常にスキップ） dry-run=%s",
        len(targets),
        len(exclude),
        args.dry_run,
    )
    for t in targets[:50]:
        logger.info("  → %s sku=%r", t["item_id"], (t["sku"] or "")[:60])
    if len(targets) > 50:
        logger.info("  … 他 %s 件", len(targets) - 50)

    ended = 0
    failed = 0
    n = 0
    for t in targets:
        if args.limit and n >= args.limit:
            break
        n += 1
        iid = t["item_id"]
        if args.dry_run:
            logger.info("[dry-run] EndFixedPriceItem %s", iid)
            continue
        res = end_fixed_price_listing(iid)
        if res.get("success"):
            ended += 1
        else:
            failed += 1
        time.sleep(0.45)

    logger.info("=== 完了 === 試行=%s 成功=%s 失敗=%s", n, ended, failed)
    return 0 if failed == 0 or args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
