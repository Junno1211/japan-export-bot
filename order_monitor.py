from __future__ import annotations

import os
import sys
import json
import logging
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from requests.exceptions import RequestException

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import EBAY_AUTH_TOKEN, EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID, EBAY_SITE_ID, EBAY_ENV
try:
    from config import SLACK_WEBHOOK_URL_ORDERS as SLACK_WEBHOOK_URL
except ImportError:
    from config import SLACK_WEBHOOK_URL
import sheets_manager
from mercari_checker import check_mercari_status
from ebay_updater import mark_out_of_stock

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROCESSED_ORDERS_FILE = os.path.join(os.path.dirname(__file__), "processed_orders.json")

def send_slack(text: str):
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL is not set.")
        return
    requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)

def load_processed() -> set:
    if os.path.exists(PROCESSED_ORDERS_FILE):
        with open(PROCESSED_ORDERS_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_processed(orders: set):
    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(PROCESSED_ORDERS_FILE), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(list(orders), f)
        os.replace(tmp_path, PROCESSED_ORDERS_FILE)
    except:
        os.unlink(tmp_path)
        raise

def get_recent_orders():
    endpoint = "https://api.ebay.com/ws/api.dll" if EBAY_ENV == "production" else "https://api.sandbox.ebay.com/ws/api.dll"
    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "GetOrders",
        "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml",
    }
    
    now = datetime.now(timezone.utc)
    from_time = (now - timedelta(days=2)).replace(microsecond=0).isoformat()
    to_time = now.replace(microsecond=0).isoformat()
    
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetOrdersRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <CreateTimeFrom>{from_time}</CreateTimeFrom>
  <CreateTimeTo>{to_time}</CreateTimeTo>
  <OrderRole>Seller</OrderRole>
  <OrderStatus>Completed</OrderStatus>
</GetOrdersRequest>"""

    last_exc: Exception | None = None
    resp = None
    for attempt in range(3):
        try:
            resp = requests.post(
                endpoint, headers=headers, data=xml_body.encode("utf-8"), timeout=45
            )
            if resp.status_code == 429:
                from utils.phase0_guards import rate_limit_guard

                rate_limit_guard(resp, "eBay Trading:GetOrders")
            break
        except RequestException as e:
            last_exc = e
            logger.warning(f"GetOrders 接続失敗 attempt {attempt + 1}/3: {e}")
            time.sleep(2 * (attempt + 1))
    if resp is None:
        logger.error(f"GetOrders リクエスト失敗（リトライ後）: {last_exc}")
        return []

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as e:
        logger.error(f"GetOrders 応答XML解析失敗: {e} body[:500]={resp.text[:500]!r}")
        return []

    ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}

    ack = root.find("ns:Ack", ns)
    if ack is None or ack.text not in ("Success", "Warning"):
        logger.error(f"GetOrders API Error: {resp.text[:500]}")
        return []
        
    orders = []
    order_array = root.find("ns:OrderArray", ns)
    if order_array is not None:
        for order in order_array.findall("ns:Order", ns):
            status = order.find("ns:OrderStatus", ns)
            if status is not None and status.text == "Completed":
                checkout = order.find("ns:CheckoutStatus/ns:Status", ns)
                if checkout is not None and checkout.text == "Complete":
                    order_id = order.find("ns:OrderID", ns).text
                    transactions = order.findall("ns:TransactionArray/ns:Transaction", ns)
                    for t in transactions:
                        item = t.find("ns:Item", ns)
                        item_id = item.find("ns:ItemID", ns).text if item is not None else "Unknown"
                        title = item.find("ns:Title", ns).text if item is not None else "Unknown Item"
                        sku = item.find("ns:SKU", ns).text if item is not None and item.find("ns:SKU", ns) is not None else ""
                        price = t.find("ns:TransactionPrice", ns).text
                        orders.append({
                            "order_id": order_id,
                            "item_id": item_id,
                            "title": title,
                            "price": price,
                            "sku": sku
                        })
    return orders

def find_source_url_from_sheets(item_id: str) -> str:
    """在庫管理表からeBay ItemIDに対応する仕入先URLを取得"""
    try:
        from config import SPREADSHEET_ID
        service = sheets_manager._get_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='在庫管理表!A2:D5000'
        ).execute()
        rows = result.get('values', [])
        for row in rows:
            if len(row) > 3 and row[0].strip() == str(item_id):
                return row[3].strip()  # D列: 仕入先URL
    except Exception as e:
        logger.error(f"Sheet search error: {e}")
    return "仕入先URL特定できず"


def translate_title_to_japanese(english_title: str) -> str:
    """Gemini APIで商品タイトルを日本語に翻訳"""
    try:
        from config import GEMINI_API_KEY
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
        prompt = f"以下のeBay商品タイトルを日本語に翻訳してください。翻訳文のみ返してください: {english_title}"
        resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
        if resp.status_code == 200:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except:
        pass
    return english_title

def main():
    orders = get_recent_orders()
    processed = load_processed()
    new_finds = False
    
    for o in orders:
        uid = f"{o['order_id']}_{o['item_id']}"
        if uid in processed:
            continue

        logger.info(f"New Order Found! {o['title']} (${o['price']})")
        source_url = o['sku']
        if not source_url or not source_url.startswith("http"):
            source_url = find_source_url_from_sheets(o['item_id'])

        # 日本語翻訳
        title_ja = translate_title_to_japanese(o['title'])

        # ★ メルカリ在庫を即座にチェック
        mercari_available = True
        if source_url and source_url.startswith("http") and "mercari" in source_url:
            try:
                stock_check = check_mercari_status(source_url, delay=0.5)
                mercari_status = stock_check.get("status", "error")
                logger.info(f"  Mercari stock check: {mercari_status}")
                if mercari_status in ("sold_out", "deleted"):
                    mercari_available = False
            except Exception as e:
                logger.error(f"  Mercari check failed: {e}")

        # 注文確定時は eBay 在庫0を 1 回だけ実行。
        # （git blame 同一コミットで分岐内と末尾に mark が二重に入っていたため統合）
        try:
            mark_out_of_stock(o["item_id"])
            logger.info(f"  eBay在庫0: {o['item_id']}")
        except Exception as e:
            logger.error(f"  eBay在庫0失敗: {e}")

        if mercari_available:
            msg = (
                f"*🚨 売れました！仕入れてください*\n"
                f"{title_ja}\n"
                f"売上: ${o['price']}\n"
                f"仕入先: {source_url}"
            )
        else:
            logger.warning(f"  ⚠️ メルカリ在庫なし（eBay在庫0は上で実行済）: {o['item_id']}")
            msg = (
                f"*🔴 売れたけどメルカリ在庫なし！*\n"
                f"{title_ja}\n"
                f"売上: ${o['price']}\n"
                f"仕入先: {source_url}\n"
                f"→ eBay在庫0を適用済み。代替品を探すかキャンセル検討してください"
            )

        send_slack(msg)

        # SOLD記録: items.csvに記録して2重販売を防止
        if source_url and source_url.startswith("http"):
            try:
                import csv as _csv
                csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "items.csv")
                # 既に存在するか確認
                existing = set()
                if os.path.exists(csv_path):
                    with open(csv_path, "r", encoding="utf-8") as _f:
                        for _row in _csv.DictReader(_f):
                            existing.add(_row.get("mercari_url", "").strip())
                if source_url.strip() not in existing:
                    with open(csv_path, "a", encoding="utf-8", newline="") as _f:
                        writer = _csv.writer(_f)
                        writer.writerow([source_url.strip(), o["item_id"], o["title"][:50], "SOLD"])
                    logger.info(f"  📝 SOLD記録: {source_url[:50]}")
            except Exception as e:
                logger.error(f"  SOLD記録失敗: {e}")

        processed.add(uid)
        new_finds = True
        
    if new_finds:
        save_processed(processed)
        
if __name__ == "__main__":
    main()
