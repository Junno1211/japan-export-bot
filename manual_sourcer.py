import time
import re
import logging
from playwright.sync_api import sync_playwright
from sheets_manager import _get_service, SPREADSHEET_ID
from auto_sourcer import append_to_sheet, EXCHANGE_RATE
from ebay_price_checker import get_market_price

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MANUAL_SHEET_NAME = "手動出品"

def calculate_manual_price_usd(mercari_price_jpy: int, target_profit_jpy: int) -> float:
    # 逆算ロジック:
    # 利益 = (USD売上 * 0.98 * 為替) - (USD売上 * 1.1 * 1.35%) - (USD売上 * 1.1 * 13.25%) - (USD売上 * 3%) - 仕入 - 実質送料3000 + ポイント
    # 利益 = USD売上 * ( 0.98 * 為替 - 為替*0.01485 - 為替*0.14575 - 為替*0.03 ) - 仕入 - 3000 + (仕入*0.1)
    # USD売上 = (仕入 + 3000 - ポイント + 目標利益) / (為替 * (0.98 - 0.01485 - 0.14575 - 0.03))
    
    net_ratio = 0.98 - (1.10 * 0.0135) - (1.10 * 0.1325) - 0.030
    points = mercari_price_jpy * 0.10
    shipping_cost = 3000
    
    required_jpy_revenue = mercari_price_jpy + shipping_cost - points + target_profit_jpy
    required_usd_revenue = required_jpy_revenue / (EXCHANGE_RATE * net_ratio)
    
    return round(required_usd_revenue, 2)

def calculate_actual_jpy_profit(ebay_usd: float, mercari_jpy: int) -> int:
    net_ratio = 0.98 - (1.10 * 0.0135) - (1.10 * 0.1325) - 0.030
    points = mercari_jpy * 0.10
    shipping_cost = 3000
    profit = (ebay_usd * EXCHANGE_RATE * net_ratio) - mercari_jpy - shipping_cost + points
    return int(profit)

import google.generativeai as genai
from config import GEMINI_API_KEY
genai.configure(api_key=GEMINI_API_KEY)

def generate_english_keyword(japanese_title: str) -> str:
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        prompt = f"Convert this Japanese product title into a highly concise, 3-5 word English search string for an eBay Search API. Only return the final English string, no quotes.\n\nTitle: {japanese_title}"
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini Keyword Error: {e}")
        return ""

def process_manual_urls():
    service = _get_service()
    range_name = f"'{MANUAL_SHEET_NAME}'!A2:D500"
    
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name
        ).execute()
        rows = result.get('values', [])
    except Exception as e:
        logger.error(f"Cannot read {MANUAL_SHEET_NAME}: {e}")
        return

    updates = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()

        for idx, row in enumerate(rows):
            # Extend row to have 4 columns
            while len(row) < 4:
                row.append("")
                
            url = row[0].strip()
            target_profit_str = row[1].strip()
            status = row[2].strip()
            
            if not url or status in ("完了", "転送完了", "自動出品シートへ移行済", "処理中"):
                continue
                
            row_num = idx + 2
            logger.info(f"Processing row {row_num}: {url}")
            
            # Update status to processing
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{MANUAL_SHEET_NAME}'!C{row_num}",
                valueInputOption="RAW",
                body={"values": [["処理中"]]}
            ).execute()
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)
                
                # Fetch Title
                title_elem = page.query_selector('h1[data-testid="name"]')
                if not title_elem:
                    title_elem = page.query_selector('h1')
                title = title_elem.inner_text().strip() if title_elem else "Unknown Title"
                
                # Fetch Price
                price_elem = page.query_selector('div[data-testid="price"] span[class*="number"]')
                if not price_elem:
                    price_elem = page.query_selector('div[data-testid="price"]')
                    
                price_text = price_elem.inner_text().replace(',', '').replace('¥', '').strip() if price_elem else "0"
                mercari_price = int(re.sub(r'[^0-9]', '', price_text)) if price_text else 0
                
                if mercari_price == 0:
                    raise ValueError("Could not extract price from page.")
                
                target_profit = int(target_profit_str) if target_profit_str.isdigit() else 10000
                initial_usd_price = calculate_manual_price_usd(mercari_price, target_profit)
                
                logger.info(f"Extracted: {title} | Price: ¥{mercari_price} | target: ${initial_usd_price}")
                
                # 競合チェック (薄利多売の調整)
                eng_keyword = generate_english_keyword(title)
                final_ebay_usd = initial_usd_price
                comp_status_msg = ""
                
                if eng_keyword:
                    market_avg = get_market_price(eng_keyword)
                    if market_avg and market_avg > 0:
                        if initial_usd_price > market_avg:
                            # 競合のほうが安い場合、競合に価格を合わせて薄利多売を狙う (競合の98%の価格に設定)
                            adjusted_price = round(market_avg * 0.98, 2)
                            new_profit = calculate_actual_jpy_profit(adjusted_price, mercari_price)
                            
                            if new_profit >= 1000:
                                final_ebay_usd = adjusted_price
                                comp_status_msg = f" (競合相場 ${market_avg:.2f} に合わせました。調整後利益: ¥{new_profit})"
                                logger.info(f"Price adjusted to beat market: ${final_ebay_usd} | New Profit: ¥{new_profit}")
                            else:
                                # 下げると利益が1000円を切る(赤字や超薄利)場合は破棄
                                raise ValueError(f"競合と価格差が大きすぎます(相場: ${market_avg:.2f})。合わせると利益が¥{new_profit}になるため出品をスキップしました。")
                        else:
                            # すでに競合より安い場合はそのまま出品（安さで勝っている）
                            comp_status_msg = f" (相場 ${market_avg:.2f} より安く勝ち確定！)"
                            logger.info("Winning on price already. Keeping initial target.")
                
                # Append to Pending Sheet
                vip_title = f"[VIP] {eng_keyword if eng_keyword else title}"
                append_to_sheet(url, vip_title, mercari_price, final_ebay_usd, target_profit)
                
                # Mark Complete
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"'{MANUAL_SHEET_NAME}'!C{row_num}:D{row_num}",
                    valueInputOption="RAW",
                    body={"values": [["自動出品シートへ移行済", f"eBay自動出品機能の「順番待ちリスト」の一番上にセットしました！(${final_ebay_usd}){comp_status_msg}"]]}
                ).execute()
                
                # Mark Complete (First logic resolves successfully)
                
            except Exception as e:
                logger.error(f"Error processing {url}: {e}")
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"'{MANUAL_SHEET_NAME}'!C{row_num}:D{row_num}",
                    valueInputOption="RAW",
                    body={"values": [["エラー", str(e)]]}
                ).execute()

        browser.close()

if __name__ == "__main__":
    logger.info("Starting Manual Sourcer...")
    process_manual_urls()
    logger.info("Done.")
