import sys
import time
import logging
import requests
import xml.etree.ElementTree as ET
from config import EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID, EBAY_ENV
from sheets_manager import read_all_items, _get_service, SPREADSHEET_ID, SHEET_NAME

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

ENDPOINTS = {
    "production": "https://api.ebay.com/ws/api.dll",
    "sandbox":    "https://api.sandbox.ebay.com/ws/api.dll"
}

def _make_headers(call_name: str) -> dict:
    return {
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": call_name,
        "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml",
    }

def end_item(item_id: str) -> bool:
    endpoint = ENDPOINTS.get(EBAY_ENV, ENDPOINTS["production"])
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<EndFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <EndingReason>NotAvailable</EndingReason>
</EndFixedPriceItemRequest>"""

    try:
        response = requests.post(
            endpoint,
            headers=_make_headers("EndFixedPriceItem"),
            data=xml_body.encode("utf-8"),
            timeout=30
        )
        response.raise_for_status()
        root = ET.fromstring(response.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
        ack = root.find("ns:Ack", ns)
        if ack is not None and ack.text in ("Success", "Warning"):
            logger.info(f"✅ 削除成功: {item_id}")
            return True
        else:
            errors = root.findall(".//ns:Errors", ns)
            error_msgs = [e.find("ns:LongMessage", ns).text for e in errors if e.find("ns:LongMessage", ns) is not None]
            logger.error(f"❌ 削除失敗 {item_id}: {' / '.join(error_msgs)}")
            # Already ended items might throw errors, which is practically a success for our goal
            if any("already ended" in msg.lower() for msg in error_msgs):
                return True
            return False
    except Exception as e:
        logger.error(f"❌ API呼び出しエラー {item_id}: {e}")
        return False

def purge_inventory():
    logger.info("🔥 既存の出品リスト 全件強制削除スクリプト 起動 🔥")
    
    items = read_all_items()
    active_items = [i for i in items if i.get("status", "").lower() == "active" and i.get("ebay_item_id")]
    
    logger.info(f"削除対象: {len(active_items)}件")
    if not active_items:
        logger.info("対象なし。終了します。")
        return

    service = _get_service()
    deleted_count = 0
    
    for item in active_items:
        item_id = item["ebay_item_id"]
        row = item["row"]
        
        logger.info(f"削除処理中: {item_id} (Spreadsheet Row: {row})")
        if end_item(item_id):
            deleted_count += 1
            # Update Sheet to reflect deletion
            try:
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"{SHEET_NAME}!F{row}",
                    valueInputOption="USER_ENTERED",
                    body={"values": [["🚫 強制削除済（SEO非最適化）"]]}
                ).execute()
            except Exception as e:
                logger.error(f"  ❌ シート更新エラー: {e}")
        
        time.sleep(1) # Prevent API rate limits

    logger.info(f"🏁 全件削除完了。 {deleted_count}/{len(active_items)} 件が正常に削除されました。")

if __name__ == "__main__":
    purge_inventory()
