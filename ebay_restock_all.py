import logging
import sys
import time
import requests
import xml.etree.ElementTree as ET
from config import (
    EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID,
    EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV
)
from mercari_checker import check_mercari_status
from ebay_updater import set_quantity
from sold_tracker import get_sold_ebay_ids

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

EBAY_ENDPOINT = {
    "production": "https://api.ebay.com/ws/api.dll",
    "sandbox":    "https://api.sandbox.ebay.com/ws/api.dll"
}.get(EBAY_ENV, "https://api.ebay.com/ws/api.dll")

def get_oos_items_from_myebay():
    """eBay からアクティブ出品のうち在庫０のものを全取得する"""
    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "GetMyeBaySelling",
        "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml",
    }
    
    oos_items = []
    
    # ページング対応
    for page in range(1, 5): # 最大800件まで (200 * 4)
        xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <ActiveList>
    <Include>true</Include>
    <Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>
  </ActiveList>
  <DetailLevel>ReturnAll</DetailLevel>
</GetMyeBaySellingRequest>"""

        try:
            resp = requests.post(EBAY_ENDPOINT, headers=headers, data=xml_body.encode("utf-8"), timeout=60)
            root = ET.fromstring(resp.text)
            ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
            
            items = root.findall(".//ns:Item", ns)
            if not items: break
            
            for item_el in items:
                ebay_id = item_el.find("ns:ItemID", ns).text
                sku_el = item_el.find("ns:SKU", ns)
                sku = sku_el.text if sku_el is not None else ""
                
                qty_el = item_el.find("ns:QuantityAvailable", ns)
                if qty_el is None: qty_el = item_el.find("ns:Quantity", ns)
                qty = int(qty_el.text) if qty_el is not None else 1
                
                if qty == 0 and "mercari" in sku:
                    oos_items.append({"ebay_id": ebay_id, "mercari_url": sku})
        except Exception as e:
            logger.error(f"Page {page} read failed: {e}")
            break
            
    return oos_items

def run_direct_recovery():
    logger.info("🚀 Surgical eBay Restock Recovery Mission Starting...")

    # SOLD済みIDを一括取得（2重販売防止）
    sold_ids = get_sold_ebay_ids()
    logger.info(f"SOLD済み商品: {len(sold_ids)}件（リストック対象外）")

    oos_items = get_oos_items_from_myebay()
    logger.info(f"Detected {len(oos_items)} candidates in ActiveList with 0 quantity.")

    restored = 0
    skipped_sold = 0
    for i, item in enumerate(oos_items):
        ebay_id = item["ebay_id"]
        url = item["mercari_url"]

        # SOLD済み商品は絶対にリストックしない（2重販売防止）
        if ebay_id in sold_ids:
            skipped_sold += 1
            logger.info(f"  ⛔ SOLD済み→リストック禁止: {ebay_id}")
            continue

        logger.info(f"[{i+1}/{len(oos_items)}] Checking: {ebay_id}")

        # メルカリチェック（高速化のため delay 0.3）
        res = check_mercari_status(url, delay=0.3)
        if res["status"] == "active":
            logger.info(f"  ✨ Mercari ACTIVE! Restocking eBay...")
            res_ebay = set_quantity(ebay_id, 1)
            if res_ebay["success"]:
                restored += 1
                logger.info(f"  ✅ Restocked Successfully")
            else:
                logger.warning(f"  ⚠️ Skip: {res_ebay.get('message')}")
        else:
            logger.info(f"  SKIP: Mercari item is {res['status']}")

    logger.info(f"🏁 Mission Complete. Restored: {restored} / SOLD skip: {skipped_sold}")

if __name__ == "__main__":
    run_direct_recovery()
