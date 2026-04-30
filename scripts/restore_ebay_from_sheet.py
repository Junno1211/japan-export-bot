#!/usr/bin/env python3
"""
在庫管理表（config.SHEET_NAME）を読み、メルカリに在庫がある行だけ eBay 数量を 1 に戻す。

ルールは inventory_manager.safe_restock と同一:
  - items.csv で SOLD 記録済み URL は復旧しない
  - 実ページに「購入手続きへ」があるときのみ ReviseFixedPriceItem Quantity=1（safe_restock）

使い方:
  cd 海外輸出ボット
  python3 scripts/restore_ebay_from_sheet.py
  python3 scripts/restore_ebay_from_sheet.py --dry-run
  python3 scripts/restore_ebay_from_sheet.py --set-sheet-active
  python3 scripts/restore_ebay_from_sheet.py --limit 30
  python3 scripts/restore_ebay_from_sheet.py --from-items-csv   # シートが空でも items.csv から

在庫チェック（inventory_manager）と同時に動かさないこと。
"""
from __future__ import annotations

import argparse
import fcntl
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
logger = logging.getLogger("restore_ebay_sheet")

LOCK_PATH = "/tmp/restore_ebay_from_sheet.lock"


def _load_from_items_csv(csv_path: str) -> list[dict]:
    import csv

    out: list[dict] = []
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = (row.get("mercari_url") or "").strip()
            eid = (row.get("ebay_item_id") or "").strip()
            st = (row.get("status") or "").strip().upper()
            if not url or not eid:
                continue
            if st == "SOLD" or "SOLD" in st:
                continue
            out.append(
                {
                    "row": None,
                    "mercari_url": url,
                    "ebay_item_id": eid,
                    "status": "",
                }
            )
    return out


def _eligible_sheet_status(status: str) -> bool:
    """Active / OutOfStock 等は対象。ENDED_*・売切・オークション終了は除外。"""
    s = (status or "").strip()
    if not s:
        return True
    low = s.lower()
    if low.startswith("ended") or "ended" in low:
        return False
    if "売切" in s or "オークション" in s:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="在庫管理表に基づき、メルカリ在庫ありなら eBay を 1 に復旧",
    )
    parser.add_argument("--limit", type=int, default=0, help="最大処理件数（0=全件）")
    parser.add_argument("--dry-run", action="store_true", help="対象だけ表示し API しない")
    parser.add_argument(
        "--skip-ebay-qty-check",
        action="store_true",
        help="GetItem を省略（件数多いとき API 節約。初回は付けない推奨）",
    )
    parser.add_argument(
        "--only-active",
        action="store_true",
        help="シートの Status が Active の行のみ",
    )
    parser.add_argument(
        "--set-sheet-active",
        action="store_true",
        help="復旧成功した行の F 列を Active に更新",
    )
    parser.add_argument(
        "--from-items-csv",
        action="store_true",
        help="在庫管理表の代わりに items.csv（status≠SOLD）を使う",
    )
    args = parser.parse_args()

    lock_f = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.error("在庫チェックまたは別の復旧が実行中です。終了してから再実行してください。")
        return 1

    try:
        from config import ITEMS_CSV_PATH, SHEET_NAME
        from ebay_updater import get_item_status
        from inventory_manager import safe_restock
        from sheets_manager import batch_update_statuses, read_all_items

        if args.from_items_csv:
            csv_abs = (
                ITEMS_CSV_PATH
                if os.path.isabs(ITEMS_CSV_PATH)
                else os.path.join(ROOT, ITEMS_CSV_PATH.lstrip("./"))
            )
            candidates = _load_from_items_csv(csv_abs)
            logger.info("items.csv 対象: %s 件（%s）", len(candidates), csv_abs)
        else:
            rows = read_all_items(SHEET_NAME)
            candidates = []
            for item in rows:
                if not item.get("mercari_url") or not item.get("ebay_item_id"):
                    continue
                st = item.get("status", "")
                if args.only_active:
                    if st.strip().lower() != "active":
                        continue
                elif not _eligible_sheet_status(st):
                    continue
                candidates.append(item)

            logger.info(
                "在庫管理表 対象: %s 件（%s）",
                len(candidates),
                "Active のみ" if args.only_active else "ENDED 系以外",
            )

        done = 0
        restored = 0
        skipped_stocked = 0
        skipped_ended = 0
        skipped_restock = 0
        failed_get = 0
        sheet_pending: list[dict] = []

        def _flush_sheet() -> None:
            if not sheet_pending:
                return
            batch_update_statuses(sheet_pending)
            sheet_pending.clear()

        for item in candidates:
            if args.limit and done >= args.limit:
                break
            ebay_id = item["ebay_item_id"].strip()
            url = item["mercari_url"].strip()
            done += 1

            if args.dry_run:
                logger.info(
                    "[dry-run] sheet_row=%s ebay=%s status=%s url=%s...",
                    item.get("row"),
                    ebay_id,
                    item.get("status", ""),
                    url[:55],
                )
                continue

            try_restock = True
            if not args.skip_ebay_qty_check:
                gst = get_item_status(ebay_id)
                if not gst.get("success"):
                    logger.warning(
                        "GetItem 失敗 — safe_restock で復旧試行: %s",
                        ebay_id,
                    )
                    failed_get += 1
                    time.sleep(0.3)
                else:
                    ls = (gst.get("listing_status") or "").lower()
                    if "completed" in ls or "ended" in ls:
                        skipped_ended += 1
                        try_restock = False
                        time.sleep(0.2)
                    elif int(gst.get("quantity", 0) or 0) >= 1:
                        skipped_stocked += 1
                        try_restock = False
                        time.sleep(0.15)

            if not try_restock:
                continue

            res = safe_restock(ebay_id, url)
            if res.get("success"):
                restored += 1
                if args.set_sheet_active and item.get("row") is not None:
                    sheet_pending.append(
                        {"row": item["row"], "status": "Active", "sheet_name": SHEET_NAME},
                    )
                    if len(sheet_pending) >= 15:
                        _flush_sheet()
            else:
                skipped_restock += 1
                why = res.get("reason") or res.get("message") or res
                logger.info("復旧せず: %s — %s...", why, url[:48])
            time.sleep(1.1)

        _flush_sheet()

        logger.info(
            "=== 完了 === 試行=%s 復旧成功=%s 既に数量>=1=%s eBay終了済スキップ=%s "
            "復旧不可=%s GetItem失敗=%s",
            done,
            restored,
            skipped_stocked,
            skipped_ended,
            skipped_restock,
            failed_get,
        )
        return 0
    finally:
        try:
            fcntl.flock(lock_f, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            lock_f.close()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
