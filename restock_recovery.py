import logging
import sys
import time
from sheets_manager import read_all_items, _get_service, SPREADSHEET_ID, SHEET_NAME
from mercari_checker import check_mercari_status
from ebay_updater import mark_out_of_stock, mark_in_stock
from sold_tracker import is_sold, get_sold_ebay_ids

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

def run_restock_recovery():
    logger.info("🚀 Aggressive Catalog Restock Mission Starting...")
    service = _get_service()
    
    # 1. 在庫管理表から全商品を読み込む (少し多めに取得)
    res = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A2:G500"
    ).execute()
    rows = res.get("values", [])
    
    logger.info(f"Checking {len(rows)} potential items...")
    
    # SOLD済みeBay IDを一括取得（2重販売防止）
    sold_ids = get_sold_ebay_ids()
    logger.info(f"SOLD済み商品: {len(sold_ids)}件（リストック対象外）")

    restored_count = 0
    skipped_sold = 0
    for i, row in enumerate(rows):
        if len(row) < 7: continue

        ebay_id = row[1].strip()     # B列
        mercari_url = row[6].strip() # G列
        current_status = row[5]      # F列

        if not ebay_id or not ebay_id.isdigit(): continue
        if not mercari_url or "mercari" not in mercari_url: continue

        # SOLD済み商品は絶対にリストックしない（2重販売防止）
        if ebay_id in sold_ids:
            skipped_sold += 1
            logger.info(f"  ⛔ SOLD済み→リストック禁止: {ebay_id}")
            continue

        logger.info(f"[{i+1}/{len(rows)}] 検証中: {ebay_id} ({current_status})")

        # メルカリの真実をチェック
        check_res = check_mercari_status(mercari_url, delay=0.5)

        if check_res["status"] == "active":
            logger.info(f"  ✨ メルカリ在庫あり確認済。eBay Quantity -> 1 に強制復帰します。")
            res_ebay = mark_in_stock(ebay_id, 1)

            if res_ebay["success"]:
                # シートも「✅ 同期中」に戻す
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"{SHEET_NAME}!F{i+2}",
                    valueInputOption="USER_ENTERED",
                    body={"values": [["✅ 同期中"]]}
                ).execute()
                restored_count += 1
            else:
                logger.error(f"  ❌ eBay復帰失敗: {res_ebay.get('message')}")
        else:
            logger.info(f"  SKIP: メルカリも実際に {check_res['status']} でした。")
        
        time.sleep(0.3)

    logger.info(f"🏁 Mission Complete. Restored: {restored_count} / SOLD skip: {skipped_sold}")

if __name__ == "__main__":
    run_restock_recovery()
