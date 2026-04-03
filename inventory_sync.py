import sys
import logging
import time
from sheets_manager import read_all_items, _get_service, SPREADSHEET_ID, SHEET_NAME
from config import COL_STATUS
from mercari_checker import batch_check_mercari
from ebay_updater import mark_out_of_stock

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

def run_inventory_sync(dry_run: bool = False):
    logger.info("=" * 60)
    logger.info("🔄 在庫同期システム 起動")
    logger.info(f"   モード: {'DRY RUN（テスト）' if dry_run else '本番連携'}")
    logger.info("=" * 60)

    # 1. 在庫管理表から全商品を読み込む
    try:
        items = read_all_items()
    except Exception as e:
        logger.error(f"在庫情報の読み込みに失敗: {e}")
        return

    # 'Active' のステータスの商品のみを抽出
    active_items = [item for item in items if item.get("status", "").lower() == "active" and item.get("mercari_url") and item.get("ebay_item_id")]
    logger.info(f"同期対象のアクティブ商品数: {len(active_items)}件")

    if not active_items:
        logger.info("対象商品がありません。終了します。")
        return

    # 2. メルカリの在庫ステータスを一括チェック
    logger.info("メルカリの最新在庫状況を取得中...")
    checked_results = batch_check_mercari(active_items, delay=1.0)

    # 3. 売り切れ商品の処理
    out_of_stock_count = 0
    service = _get_service()

    for result in checked_results:
        status = result.get("status")
        mercari_url = result.get("mercari_url")
        ebay_id = result.get("ebay_item_id")
        row = result.get("row")

        if status in ("sold_out", "deleted"):
            logger.warning(f"⚠️ 売り切れ検知! メルカリ: {mercari_url} -> eBay: {ebay_id}")
            out_of_stock_count += 1
            
            if not dry_run:
                # eBayの在庫を0にする
                res = mark_out_of_stock(ebay_id)
                if res["success"]:
                    logger.info(f"  ✅ eBayの出品を終了(在庫0)にしました: {ebay_id}")
                    # スプレッドシートのステータスを更新
                    # COL_STATUS (5 = F列) をアルファベットに変換
                    status_col_letter = chr(65 + COL_STATUS)  # F
                    try:
                        service.spreadsheets().values().update(
                            spreadsheetId=SPREADSHEET_ID,
                            range=f"{SHEET_NAME}!{status_col_letter}{row}",
                            valueInputOption="USER_ENTERED",
                            body={"values": [["❌ 売り切れ(eBay終了)"]]}
                        ).execute()
                    except Exception as e:
                        logger.error(f"  ❌ シートのステータス更新に失敗: {e}")
                elif "You are not allowed to revise an ended item" in res.get("message", ""):
                    logger.info(f"  ℹ️ すでにeBay側で終了済みです: {ebay_id}. シートを更新します。")
                    status_col_letter = chr(65 + 3) # D
                    try:
                        service.spreadsheets().values().update(
                            spreadsheetId=SPREADSHEET_ID,
                            range=f"{SHEET_NAME}!{status_col_letter}{row}",
                            valueInputOption="USER_ENTERED",
                            body={"values": [["✅ 同期完了(eBay既終了)"]]}
                        ).execute()
                    except Exception as e:
                        logger.error(f"  ❌ シートのステータス更新に失敗: {e}")
                else:
                    logger.error(f"  ❌ eBayの在庫変更に失敗: {res['message']}")

    logger.info("=" * 60)
    logger.info(f"🏁 在庫同期完了 | 対象: {len(active_items)}件 | 売り切れ終了: {out_of_stock_count}件")
    logger.info("=" * 60)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="テスト実行（実際の出品終了はしない）")
    args = parser.parse_args()
    run_inventory_sync(dry_run=args.dry_run)
