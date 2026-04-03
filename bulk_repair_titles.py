import logging
import sys
import time
from playwright.sync_api import sync_playwright
from sheets_manager import _get_service, SPREADSHEET_ID
from config import LISTING_SHEET_NAME
from auto_lister import ai_analyze
from ebay_updater import revise_item_title
from mercari_scraper import scrape_mercari_item

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

def run_bulk_repair():
    logger.info("🚀 Bulk Title Repair Mission Starting (Harden v2)...")
    service = _get_service()
    
    # 在庫管理表を取得
    sheet_name = "在庫管理表"
    res = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{sheet_name}!A2:G300"
    ).execute()
    rows = res.get("values", [])
    
    repaired_count = 0
    
    # [CRITICAL FIX] Browser Reuse for VPS Stability
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        
        for i, row in enumerate(rows):
            if len(row) < 7: continue
            
            status = row[5] # F列: Status
            ebay_id = str(row[1]).strip() # B列: eBay Item ID
            current_title = row[2] # C列: Title
            mercari_url = str(row[6]).strip() # G列: Mercari URL
            
            if not ebay_id or not ebay_id.isdigit(): continue
            if "Active" not in status: continue
                
            # タイトルが短い（70文字未満）ものを対象
            if len(current_title) < 70 or "Japanese Collectible" in current_title:
                logger.info(f"📍 Repairing Row {i+2}: {current_title} ({len(current_title)} chars)")
                
                try:
                    scraped = scrape_mercari_item(mercari_url, playwright_browser=browser)
                    if not scraped.get("success"): continue
                    
                    # AI分析 (80文字ターゲット)
                    ai_data = ai_analyze(scraped["title"], scraped["description"], 100.0)
                    new_title = ai_data.get("title")
                    
                    if new_title and len(new_title) >= 70:
                        res_ebay = revise_item_title(ebay_id, new_title)
                        if res_ebay["success"]:
                            logger.info(f"  ✅ Success! New Title: {new_title}")
                            service.spreadsheets().values().update(
                                spreadsheetId=SPREADSHEET_ID,
                                range=f"{sheet_name}!C{i+2}",
                                valueInputOption="USER_ENTERED",
                                body={"values": [[new_title]]}
                            ).execute()
                            repaired_count += 1
                            time.sleep(1)
                        else:
                            logger.error(f"  ❌ eBay Error: {res_ebay.get('message')}")
                except Exception as e:
                    logger.error(f"  ❌ Error at Row {i+2}: {e}")
        
        browser.close()

    logger.info(f"🏁 Bulk Repair Complete. Items Repaired: {repaired_count}")

if __name__ == "__main__":
    run_bulk_repair()
