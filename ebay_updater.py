# ============================================================
#  ebay_updater.py  —  eBay API で在庫数を更新
# ============================================================

import logging
import requests
import xml.etree.ElementTree as ET
from config import (
    EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID,
    EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV
)

logger = logging.getLogger(__name__)

# API エンドポイント
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


def set_quantity(item_id: str, quantity: int) -> dict:
    endpoint = ENDPOINTS.get(EBAY_ENV, ENDPOINTS["production"])
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <Item>
    <ItemID>{item_id}</ItemID>
    <Quantity>{quantity}</Quantity>
  </Item>
</ReviseFixedPriceItemRequest>"""
    try:
        response = requests.post(
            endpoint,
            headers=_make_headers("ReviseFixedPriceItem"),
            data=xml_body.encode("utf-8"),
            timeout=30
        )
        root = ET.fromstring(response.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
        ack = root.find("ns:Ack", ns)
        if ack is not None and ack.text in ("Success", "Warning"):
            logger.info(f"✅ eBay Item {item_id} → quantity={quantity} 更新成功")
            return {"success": True, "message": f"Quantity set to {quantity}"}
        errors = root.findall(".//ns:Errors", ns)
        msg = " / ".join([e.find("ns:LongMessage", ns).text for e in errors if e.find("ns:LongMessage", ns) is not None])
        logger.error(f"❌ eBay API error for {item_id}: {msg}")
        logger.error(f"Full response: {response.text}")
        return {"success": False, "message": msg}
    except Exception as e:
        logger.error(f"❌ error for {item_id}: {e}")
        return {"success": False, "message": str(e)}


def mark_out_of_stock(item_id: str) -> dict:
    """在庫切れにする（quantity=0）"""
    return set_quantity(item_id, 0)


def mark_in_stock(item_id: str, quantity: int = 1) -> dict:
    """在庫復活させる（quantity=1以上）"""
    return set_quantity(item_id, quantity)


def get_item_status(item_id: str) -> dict:
    """
    eBay出品の現在状態を取得する（GetItem）
    Returns: {"success": bool, "quantity": int, "listing_status": str}
    """
    endpoint = ENDPOINTS.get(EBAY_ENV, ENDPOINTS["production"])

    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <DetailLevel>ReturnAll</DetailLevel>
</GetItemRequest>"""

    try:
        response = requests.post(
            endpoint,
            headers=_make_headers("GetItem"),
            data=xml_body.encode("utf-8"),
            timeout=30
        )
        root = ET.fromstring(response.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}

        ack = root.find("ns:Ack", ns)
        if ack is not None and ack.text in ("Success", "Warning"):
            qty_el = root.find(".//ns:Quantity", ns)
            status_el = root.find(".//ns:ListingStatus", ns)
            return {
                "success": True,
                "quantity": int(qty_el.text) if qty_el is not None else -1,
                "listing_status": status_el.text if status_el is not None else "Unknown"
            }
        return {"success": False, "quantity": -1, "listing_status": "Error"}

    except Exception as e:
        logger.error(f"GetItem error for {item_id}: {e}")
        return {"success": False, "quantity": -1, "listing_status": "Error"}
def revise_item_title(item_id: str, new_title: str) -> dict:
    """eBay出品のタイトルを更新する（Trading API: ReviseFixedPriceItem）"""
    endpoint = ENDPOINTS.get(EBAY_ENV, ENDPOINTS["production"])
    
    # XMLセーフなエスケープ
    import html
    escaped_title = html.escape(new_title)

    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <Item>
    <ItemID>{item_id}</ItemID>
    <Title>{escaped_title}</Title>
  </Item>
</ReviseFixedPriceItemRequest>"""

    try:
        response = requests.post(
            endpoint,
            headers=_make_headers("ReviseFixedPriceItem"),
            data=xml_body.encode("utf-8"),
            timeout=30
        )
        root = ET.fromstring(response.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
        ack = root.find("ns:Ack", ns)
        if ack is not None and ack.text in ("Success", "Warning"):
            logger.info(f"✅ eBay Item {item_id} のタイトルを更新しました: {new_title}")
            return {"success": True, "message": "Title updated"}
        else:
            errors = root.findall(".//ns:Errors", ns)
            msg = " / ".join([e.find("ns:LongMessage", ns).text for e in errors])
            logger.error(f"❌ eBay API error: {msg}")
            return {"success": False, "message": msg}
    except Exception as e:
        return {"success": False, "message": str(e)}
