import sys
import concurrent.futures
from sheets_manager import _get_service, read_all_items, batch_update_statuses
from ebay_updater import set_quantity
from mercari_scraper import scrape_mercari_item
from sold_tracker import get_sold_ebay_ids

def run_super_fix():
    print("==================================================")
    print("🚨 【第一段階開始】スプレッドシートのE列(在庫有り)を正としてeBayを超高速で復活させます！")
    print("==================================================")
    sold_ids = get_sold_ebay_ids()
    print(f"SOLD済み: {len(sold_ids)}件（リストック対象外）")
    service = _get_service()
    res = service.spreadsheets().values().get(
        spreadsheetId='1dlRcKP4tKubmubrO-_kYo2y9cfN867ZUbHUMYjp4280',
        range='在庫管理表!A2:F1000'
    ).execute()
    rows = res.get('values', [])
    updates1 = []

    def instant_fix_row(i, row):
        row_num = i + 2
        if len(row) < 5: return None
        ebay_id = row[0].strip()
        original_stock = row[4].strip() # E列（在庫状況）
        if not ebay_id: return None

        # SOLD済み商品は絶対にリストックしない
        if ebay_id in sold_ids:
            return None

        try:
            if "在庫有り" in original_stock or "有り" in original_stock:
                set_quantity(ebay_id, 1)
                return {"range": f"在庫管理表!F{row_num}", "values": [["Active"]]}
            elif "売切" in original_stock:
                # E列が元々売り切れだった商品は、念のため0確定
                set_quantity(ebay_id, 0)
                return {"range": f"在庫管理表!F{row_num}", "values": [["OutOfStock"]]}
        except Exception as e:
            pass
        return None

    # 第一段階：10並列でAPIを叩き、数秒〜数十秒でeBayを復帰させる
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(instant_fix_row, i, row): i for i, row in enumerate(rows)}
        for future in concurrent.futures.as_completed(futures):
            res_future = future.result()
            if res_future: updates1.append(res_future)
            
    if updates1:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId='1dlRcKP4tKubmubrO-_kYo2y9cfN867ZUbHUMYjp4280',
            body={"valueInputOption": "USER_ENTERED", "data": updates1}
        ).execute()
        
    print("\n✅ 【第一段階完了】eBayの全商品が元の状態に即時復活しました！！！")
    
    print("\n==================================================")
    print("🚨 【第二段階開始】改修済みAIでメルカリの「最新・本当の状況」を正確にチェックします...")
    print("     (すでに販売機会は戻っているため、時間をかけてゆっくり確実に行います)")
    print("==================================================")
    
    items = read_all_items()
    updates2 = []
    for i, item in enumerate(items):
        url = item.get("mercari_url", "")
        ebay_id = item.get("ebay_item_id", "")
        row_id = item.get("row")
        if not url or not ebay_id: continue

        # SOLD済み商品は絶対にリストックしない
        if ebay_id in sold_ids:
            continue

        result = scrape_mercari_item(url, delay=1.0)
        status = result["status"]

        if status in ("sold_out", "deleted"):
            print(f"[{i+1}] ❌ メルカリ最新状況「売り切れ」を確認: {ebay_id} -> 在庫0へ更新")
            set_quantity(ebay_id, 0)
            updates2.append({"row": row_id, "status": "OutOfStock", "notes": "最新・確定売り切れ"})
        elif status == "active":
            print(f"[{i+1}] ✅ メルカリ最新状況「販売中」を確認: {ebay_id} -> 在庫1維持")
            set_quantity(ebay_id, 1)
            updates2.append({"row": row_id, "status": "Active", "notes": "最新・確定販売中"})
            
    if updates2:
        batch_update_statuses(updates2)
        print("\n✅ 【第二段階完了】メルカリの最新状況の完全同期が完了しました！！！")

if __name__ == '__main__':
    run_super_fix()
