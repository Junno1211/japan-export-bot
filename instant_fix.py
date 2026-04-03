import time
import concurrent.futures
import sys
from sheets_manager import _get_service
from ebay_updater import set_quantity
from sold_tracker import get_sold_ebay_ids

def instant_restore():
    print("🚨 【緊急稼働】これより、スプレッドシートの『在庫状況（E列）』を正として全件高速復元を開始します。")
    sold_ids = get_sold_ebay_ids()
    print(f"SOLD済み: {len(sold_ids)}件（リストック対象外）")
    service = _get_service()

    res = service.spreadsheets().values().get(
        spreadsheetId='1dlRcKP4tKubmubrO-_kYo2y9cfN867ZUbHUMYjp4280',
        range='在庫管理表!A2:F1000'
    ).execute()

    rows = res.get('values', [])
    updates = []

    def fix_row(i, row):
        row_num = i + 2
        if len(row) < 5:
            return None

        ebay_id = row[0].strip()
        original_stock = row[4].strip()

        if not ebay_id:
            return None

        # SOLD済み商品は絶対にリストックしない
        if ebay_id in sold_ids:
            return None

        try:
            if "売切" in original_stock:
                # E列が売り切れの場合 -> 0
                set_quantity(ebay_id, 0)
                return {"range": f"在庫管理表!F{row_num}", "values": [["OutOfStock"]]}
            else:
                # E列が在庫有りの場合 -> 1へ強制復活！！！
                set_quantity(ebay_id, 1)
                return {"range": f"在庫管理表!F{row_num}", "values": [["Active"]]}
        except Exception as e:
            print(f"Row {row_num} Error: {e}")
            return None

    print(f"📊 処理対象: {len(rows)}行。10並列でeBayを超高速書き換え中です...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fix_row, i, row): i for i, row in enumerate(rows)}
        for count, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()
            if result:
                updates.append(result)
            if count % 20 == 0:
                print(f"🚀 {count} 件のeBay復旧が完了...")
                sys.stdout.flush()
                
    if updates:
        print("💾 全件のeBay書込完了！続いてスプレッドシートのF列（Status）を書き直します...")
        service.spreadsheets().values().batchUpdate(
            spreadsheetId='1dlRcKP4tKubmubrO-_kYo2y9cfN867ZUbHUMYjp4280',
            body={"valueInputOption": "USER_ENTERED", "data": updates}
        ).execute()
        print("✅ スプレッドシートの書き換えも完了しました！【完全復旧完了】")

if __name__ == '__main__':
    instant_restore()
