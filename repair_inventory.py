#!/usr/bin/env python3
"""
repair_inventory.py — 在庫管理表の修復 + 全件メルカリ在庫チェック

1. URL欄が壊れた行を処理（URL復元不可 → 「要手動確認」マーク）
2. 全Active商品のメルカリ在庫を一括チェック
3. 売り切れ商品 → eBay在庫0 + シートから削除
"""

import sys
import time
import logging
from sheets_manager import (
    read_all_items, _get_service, SPREADSHEET_ID, SHEET_NAME,
    delete_rows, batch_update_statuses
)
from config import COL_STATUS, COL_NOTES, COL_MERCARI_URL
from mercari_checker import check_mercari_status
from ebay_updater import mark_out_of_stock

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)


def repair():
    logger.info("=" * 60)
    logger.info("🔧 在庫管理表 修復 + 全件在庫チェック 開始")
    logger.info("=" * 60)

    items = read_all_items()
    logger.info(f"在庫管理表: 全{len(items)}件")

    service = _get_service()

    # --- Phase 1: 壊れた行を処理 ---
    broken = [i for i in items if not i["mercari_url"].startswith("http")]
    if broken:
        logger.info(f"\n--- Phase 1: 壊れた行 {len(broken)}件 を処理 ---")
        for b in broken:
            row = b["row"]
            ebay_id = b["ebay_item_id"]
            logger.warning(f"  Row:{row} | eBay:{ebay_id} | URL欄: {b['mercari_url'][:40]}")
            # G列(Notes)に「要手動確認」を書き込む
            notes_col = chr(65 + COL_NOTES)  # G
            status_col = chr(65 + COL_STATUS)  # F
            try:
                service.spreadsheets().values().batchUpdate(
                    spreadsheetId=SPREADSHEET_ID,
                    body={
                        "valueInputOption": "USER_ENTERED",
                        "data": [
                            {"range": f"{SHEET_NAME}!{status_col}{row}", "values": [["要手動確認"]]},
                            {"range": f"{SHEET_NAME}!{notes_col}{row}", "values": [["URL欄破損 - メルカリURL不明のため在庫チェック不可"]]},
                        ]
                    }
                ).execute()
            except Exception as e:
                logger.error(f"  シート更新失敗: {e}")
            time.sleep(0.3)
    else:
        logger.info("壊れた行: なし")

    # --- Phase 2: 正常な行の全件メルカリ在庫チェック ---
    valid = [i for i in items if i["mercari_url"].startswith("http") and i["ebay_item_id"]]
    logger.info(f"\n--- Phase 2: メルカリ在庫チェック {len(valid)}件 ---")

    sold_out_rows = []
    sold_out_count = 0
    active_count = 0
    error_count = 0

    for idx, item in enumerate(valid):
        url = item["mercari_url"]
        ebay_id = item["ebay_item_id"]
        row = item["row"]

        logger.info(f"[{idx+1}/{len(valid)}] Row:{row} | eBay:{ebay_id}")

        try:
            result = check_mercari_status(url, delay=1.0)
            status = result.get("status", "error")
        except Exception as e:
            logger.error(f"  チェック失敗: {e}")
            error_count += 1
            continue

        if status == "active":
            active_count += 1
            logger.info(f"  ✅ 在庫あり")
        elif status in ("sold_out", "deleted"):
            sold_out_count += 1
            logger.warning(f"  ❌ 売り切れ/削除 → eBay在庫0にします")
            res = mark_out_of_stock(ebay_id)
            if res["success"]:
                logger.info(f"  ✅ eBay在庫0完了: {ebay_id}")
                sold_out_rows.append(row)
            elif "not allowed to revise an ended item" in res.get("message", ""):
                logger.info(f"  ℹ️ eBay既終了: {ebay_id}")
                sold_out_rows.append(row)
            else:
                logger.error(f"  ❌ eBay更新失敗: {res['message']}")
                error_count += 1
        else:
            error_count += 1
            logger.warning(f"  ⚠️ チェックエラー: {status}")

    # --- Phase 3: 売り切れ行をシートから削除 ---
    if sold_out_rows:
        logger.info(f"\n--- Phase 3: 売り切れ {len(sold_out_rows)}件 をシートから削除 ---")
        try:
            delete_rows(SHEET_NAME, sold_out_rows)
            logger.info(f"✅ {len(sold_out_rows)}件 削除完了")
        except Exception as e:
            logger.error(f"削除失敗: {e}")

    # --- 結果 ---
    logger.info("\n" + "=" * 60)
    logger.info(f"🏁 修復完了")
    logger.info(f"   チェック対象: {len(valid)}件")
    logger.info(f"   在庫あり:     {active_count}件")
    logger.info(f"   売り切れ:     {sold_out_count}件（シートから削除済み）")
    logger.info(f"   エラー:       {error_count}件")
    logger.info(f"   URL破損:      {len(broken)}件（要手動確認マーク済み）")
    logger.info("=" * 60)


if __name__ == "__main__":
    repair()
