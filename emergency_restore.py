import logging
import sys
import os
from time import sleep
from sheets_manager import read_all_items, batch_update_statuses
from mercari_scraper import scrape_mercari_item
from ebay_updater import set_quantity
from sold_tracker import get_sold_ebay_ids

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

def restore_inventory():
    logger.info("🚨 復旧処理（ローカル同期）を開始します...")
    sold_ids = get_sold_ebay_ids()
    logger.info(f"SOLD済み: {len(sold_ids)}件（リストック対象外）")
    items = read_all_items()
    logger.info(f"スプレッドシートから {len(items)} 件のアイテムを読み込みました。")

    updates = []
    restored_count = 0
    kept_zero_count = 0
    skipped_sold = 0
    errors = 0

    for i, item in enumerate(items):
        url = item.get("mercari_url", "")
        ebay_id = item.get("ebay_item_id", "")
        row_id = item.get("row")

        if not url or not ebay_id:
            continue

        # SOLD済み商品は絶対にリストックしない
        if ebay_id in sold_ids:
            skipped_sold += 1
            continue
            
        logger.info(f"\n[{i+1}/{len(items)}] Row:{row_id} | eBay:{ebay_id}")
        logger.info(f"URL: {url}")
        
        # ローカルのスクレイパーで「本当のステータス」を取得
        result = scrape_mercari_item(url, delay=1.0)
        status = result["status"]
        title = result.get("title", "")
        
        if status == "active":
            logger.info(f"✅ [本物] 販売中: {title[:30]} -> eBayの在庫を [1] に強制書き戻します！")
            ebay_res = set_quantity(ebay_id, 1)
            if ebay_res["success"]:
                restored_count += 1
                updates.append({"row": row_id, "status": "Active", "notes": "復旧完了"})
            else:
                errors += 1
                updates.append({"row": row_id, "status": "Error", "notes": f"復旧失敗: {ebay_res['message']}"})
                
        elif status in ("sold_out", "deleted"):
            logger.info(f"❌ [本物] 売り切れ: {title[:30]} -> eBayの在庫 [0] を維持・再設定します。")
            set_quantity(ebay_id, 0)
            kept_zero_count += 1
            updates.append({"row": row_id, "status": "OutOfStock", "notes": "メルカリ売り切れ(確認済)"})
            
        else:
            logger.warning(f"⚠️ 取得エラー（手動確認推奨）")
            errors += 1
            
    if updates:
        batch_update_statuses(updates)
        logger.info("✅ スプレッドシートのステータスを一括更新しました！")
        
    logger.info("\n" + "="*50)
    logger.info(f"🚨 復旧処理完了！")
    logger.info(f"  - 強制復旧（在庫1に戻した数）: {restored_count}件")
    logger.info(f"  - 売り切れ維持（在庫0）      : {kept_zero_count}件")
    logger.info(f"  - エラー                     : {errors}件")
    logger.info("="*50)

if __name__ == "__main__":
    restore_inventory()
