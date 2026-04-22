# ============================================================
#  ebay_updater.py  —  eBay API で在庫数を更新
# ============================================================

import logging
import time
import requests
import xml.etree.ElementTree as ET
from config import (
    EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID,
    EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV
)

logger = logging.getLogger(__name__)

_NS = {"ns": "urn:ebay:apis:eBLBaseComponents"}


def _xml_int(el: ET.Element | None) -> int | None:
    if el is None or el.text is None:
        return None
    t = el.text.strip()
    if not t:
        return None
    try:
        return int(t)
    except ValueError:
        return None


def active_item_available_quantity(item_el: ET.Element, ns: dict | None = None) -> int:
    """
    GetMyeBaySelling の ActiveList / Item から「販売可能な残数」を推定する。

    Out-of-stock 制御の GTC では、Seller Hub は在庫0でも XML で
    Quantity が元の1のまま・QuantityAvailable が別階層や欠落、といったことがある。
    Quantity − QuantitySold、子孫ノードの QuantityAvailable、Inventory ブロックも試す。
    """
    ns = ns or _NS
    qa = _xml_int(item_el.find("ns:QuantityAvailable", ns))
    if qa is not None:
        return max(0, qa)
    ss0 = item_el.find("ns:SellingStatus", ns)
    if ss0 is not None:
        qa_ss = _xml_int(ss0.find("ns:QuantityAvailable", ns))
        if qa_ss is not None:
            return max(0, qa_ss)
    inv = item_el.find("ns:Inventory", ns)
    if inv is not None:
        qa_inv = _xml_int(inv.find("ns:QuantityAvailable", ns))
        if qa_inv is not None:
            return max(0, qa_inv)
    # Item 配下の任意の QuantityAvailable（Variation 内など）
    for qa_el in item_el.findall(".//ns:QuantityAvailable", ns):
        qa = _xml_int(qa_el)
        if qa is not None:
            return max(0, qa)
    qty = _xml_int(item_el.find("ns:Quantity", ns))
    ss = item_el.find("ns:SellingStatus", ns)
    sold = _xml_int(ss.find("ns:QuantitySold", ns)) if ss is not None else None
    if qty is not None and sold is not None:
        return max(0, qty - sold)
    if qty is not None:
        return max(0, qty)
    return -1


def _revise_error_messages(root: ET.Element) -> tuple[list[str], list[str]]:
    """(LongMessage のリスト, ErrorCode のリスト)"""
    longs: list[str] = []
    codes: list[str] = []
    for e in root.findall(".//ns:Errors", _NS):
        lm = e.find("ns:LongMessage", _NS)
        if lm is not None and lm.text:
            longs.append(lm.text)
        ce = e.find("ns:ErrorCode", _NS)
        if ce is not None and ce.text:
            codes.append(ce.text)
    return longs, codes


def _is_already_ended_listing_error(long_messages: list[str], error_codes: list[str]) -> bool:
    if "291" in error_codes:
        return True
    blob = " ".join(long_messages).lower()
    return "not allowed to revise ended" in blob or "revise ended" in blob or "auction ended" in blob


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


class EbayTradingRateLimited(RuntimeError):
    """HTTP 429 — Phase 0 で処理停止（指数バックオフは Phase 0.5）。"""


def trading_post(
    endpoint: str,
    headers: dict,
    data: bytes,
    call_name: str,
    *,
    timeout: int = 30,
) -> requests.Response:
    """
    eBay Trading API 向け POST。
    - 429: Slack 通知後に EbayTradingRateLimited で停止（リトライしない）
    - 5xx: 最大 1 回再試行
    """
    from utils.phase0_guards import rate_limit_guard

    last: requests.Response | None = None
    for attempt in range(2):
        resp = requests.post(endpoint, headers=headers, data=data, timeout=timeout)
        last = resp
        try:
            rate_limit_guard(resp, f"eBay Trading:{call_name}")
        except RuntimeError as e:
            raise EbayTradingRateLimited(str(e)) from e
        if resp.status_code >= 500 and attempt == 0:
            logger.warning("%s: HTTP %s — 5xx を1回再試行", call_name, resp.status_code)
            time.sleep(1.0)
            continue
        return resp
    assert last is not None
    return last


def revise_inventory_status_quantity(item_id: str, quantity: int) -> dict:
    """
    在庫数のみ更新（ReviseInventoryStatus）。
    在庫0で非表示になった GTC 出品の「再入荷」はこちらが有効なことが多い。
    """
    endpoint = ENDPOINTS.get(EBAY_ENV, ENDPOINTS["production"])
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseInventoryStatusRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <InventoryStatus>
    <ItemID>{item_id}</ItemID>
    <Quantity>{quantity}</Quantity>
  </InventoryStatus>
</ReviseInventoryStatusRequest>"""
    try:
        response = trading_post(
            endpoint,
            _make_headers("ReviseInventoryStatus"),
            xml_body.encode("utf-8"),
            "ReviseInventoryStatus",
            timeout=30,
        )
        root = ET.fromstring(response.text)
        ns = _NS
        ack = root.find("ns:Ack", ns)
        if ack is not None and ack.text in ("Success", "Warning"):
            logger.info(
                f"✅ eBay Item {item_id} → ReviseInventoryStatus quantity={quantity} OK"
            )
            return {"success": True, "message": f"ReviseInventoryStatus qty={quantity}"}
        longs, codes = _revise_error_messages(root)
        msg = " / ".join(longs) if longs else "Unknown eBay error"
        logger.warning(f"ReviseInventoryStatus 失敗 {item_id}: {msg}")
        return {"success": False, "message": msg}
    except EbayTradingRateLimited as e:
        logger.error("ReviseInventoryStatus: %s", e)
        return {"success": False, "message": str(e)}
    except Exception as e:
        logger.warning(f"ReviseInventoryStatus 例外 {item_id}: {e}")
        return {"success": False, "message": str(e)}


def _set_quantity_revise_fixed_price(item_id: str, quantity: int) -> dict:
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
        response = trading_post(
            endpoint,
            _make_headers("ReviseFixedPriceItem"),
            xml_body.encode("utf-8"),
            "ReviseFixedPriceItem_qty",
            timeout=30,
        )
        root = ET.fromstring(response.text)
        ns = _NS
        ack = root.find("ns:Ack", ns)
        if ack is not None and ack.text in ("Success", "Warning"):
            logger.info(f"✅ eBay Item {item_id} → quantity={quantity} 更新成功")
            return {"success": True, "message": f"Quantity set to {quantity}"}
        longs, codes = _revise_error_messages(root)
        msg = " / ".join(longs) if longs else "Unknown eBay error"
        if quantity == 0 and _is_already_ended_listing_error(longs, codes):
            logger.info(f"ℹ️ eBay Item {item_id}: 既に終了済みの出品のため在庫0更新は不要（成功扱い）")
            return {"success": True, "message": "already_ended", "already_ended": True}
        logger.error(f"❌ eBay API error for {item_id}: {msg}")
        logger.error(f"Full response: {response.text}")
        return {"success": False, "message": msg}
    except EbayTradingRateLimited as e:
        logger.error("ReviseFixedPriceItem: %s", e)
        return {"success": False, "message": str(e)}
    except Exception as e:
        logger.error(f"❌ error for {item_id}: {e}")
        return {"success": False, "message": str(e)}


def set_quantity(item_id: str, quantity: int) -> dict:
    """
    在庫数を更新。在庫0→正数の再入荷では ReviseInventoryStatus を先に試し、
    ダメなら ReviseFixedPriceItem（従来）。
    """
    if quantity > 0:
        inv = revise_inventory_status_quantity(item_id, quantity)
        if inv.get("success"):
            return inv
        logger.info(f"ReviseInventoryStatus で失敗のため ReviseFixedPriceItem にフォールバック: {item_id}")
    return _set_quantity_revise_fixed_price(item_id, quantity)


def set_quantity_revise_only(item_id: str, quantity: int) -> dict:
    """ReviseFixedPriceItem のみ（旧 set_quantity と同等の単一路線）。"""
    return _set_quantity_revise_fixed_price(item_id, quantity)


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
        response = trading_post(
            endpoint,
            _make_headers("GetItem"),
            xml_body.encode("utf-8"),
            "GetItem",
            timeout=30,
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

    except EbayTradingRateLimited as e:
        logger.error("GetItem: %s", e)
        return {"success": False, "quantity": -1, "listing_status": "RateLimited"}
    except Exception as e:
        logger.error(f"GetItem error for {item_id}: {e}")
        return {"success": False, "quantity": -1, "listing_status": "Error"}


def get_all_active_list_items() -> list[dict]:
    """
    GetMyeBaySelling の ActiveList をページングで全取得。
    各 dict: item_id, quantity, sku（Seller Hub のアクティブ一覧と対応）。
    """
    endpoint = ENDPOINTS.get(EBAY_ENV, ENDPOINTS["production"])
    out: list[dict] = []
    ns = _NS
    for page in range(1, 30):
        xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <ActiveList>
    <Include>true</Include>
    <Pagination>
      <EntriesPerPage>200</EntriesPerPage>
      <PageNumber>{page}</PageNumber>
    </Pagination>
  </ActiveList>
  <DetailLevel>ReturnAll</DetailLevel>
</GetMyeBaySellingRequest>"""
        try:
            response = trading_post(
                endpoint,
                _make_headers("GetMyeBaySelling"),
                xml_body.encode("utf-8"),
                f"GetMyeBaySelling_p{page}",
                timeout=90,
            )
            root = ET.fromstring(response.text)
            ack = root.find("ns:Ack", ns)
            if ack is not None and ack.text not in ("Success", "Warning"):
                logger.warning("GetMyeBaySelling Ack: %s", ack.text if ack is not None else "?")
            items = root.findall(".//ns:ActiveList//ns:Item", ns)
            if not items:
                break
            for item_el in items:
                ebay_id_el = item_el.find("ns:ItemID", ns)
                sku_el = item_el.find("ns:SKU", ns)
                eid = ebay_id_el.text.strip() if ebay_id_el is not None and ebay_id_el.text else ""
                if not eid:
                    continue
                q = active_item_available_quantity(item_el, ns)
                out.append(
                    {
                        "item_id": eid,
                        "quantity": q,
                        "sku": sku_el.text if sku_el is not None else "",
                    }
                )
            total_pages_el = root.find(
                ".//ns:ActiveList/ns:PaginationResult/ns:TotalNumberOfPages", ns
            )
            if total_pages_el is not None and total_pages_el.text:
                try:
                    if page >= int(total_pages_el.text):
                        break
                except ValueError:
                    pass
            time.sleep(0.4)
        except EbayTradingRateLimited:
            logger.error("GetMyeBaySelling: rate limited on page %s — 取得中断", page)
            break
        except Exception as e:
            logger.error("GetMyeBaySelling page %s: %s", page, e)
            break
    return out


def end_fixed_price_listing(
    item_id: str,
    ending_reason: str = "NotAvailable",
) -> dict:
    """
    固定価格出品を終了する（EndFixedPriceItem）。在庫0のゴミ出品を消す用途。
    ending_reason: NotAvailable / LostOrBroken / Sold / Incorrect / OtherListingError
    """
    endpoint = ENDPOINTS.get(EBAY_ENV, ENDPOINTS["production"])
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<EndFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <EndingReason>{ending_reason}</EndingReason>
</EndFixedPriceItemRequest>"""
    try:
        response = trading_post(
            endpoint,
            _make_headers("EndFixedPriceItem"),
            xml_body.encode("utf-8"),
            "EndFixedPriceItem",
            timeout=30,
        )
        root = ET.fromstring(response.text)
        ns = _NS
        ack = root.find("ns:Ack", ns)
        if ack is not None and ack.text in ("Success", "Warning"):
            logger.info(f"✅ eBay Item {item_id} 出品終了 OK")
            return {"success": True, "message": "ended"}
        longs, codes = _revise_error_messages(root)
        msg = " / ".join(longs) if longs else "Unknown eBay error"
        blob = " ".join(longs).lower()
        if "already ended" in blob or "listing has ended" in blob or "291" in codes:
            logger.info(f"ℹ️ eBay Item {item_id}: 既に終了済み")
            return {"success": True, "message": "already_ended"}
        logger.error(f"❌ EndFixedPriceItem {item_id}: {msg}")
        return {"success": False, "message": msg}
    except EbayTradingRateLimited as e:
        logger.error("EndFixedPriceItem: %s", e)
        return {"success": False, "message": str(e)}
    except Exception as e:
        logger.error(f"❌ EndFixedPriceItem error {item_id}: {e}")
        return {"success": False, "message": str(e)}


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
        response = trading_post(
            endpoint,
            _make_headers("ReviseFixedPriceItem"),
            xml_body.encode("utf-8"),
            "ReviseFixedPriceItem_title",
            timeout=30,
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
    except EbayTradingRateLimited as e:
        logger.error("revise_item_title: %s", e)
        return {"success": False, "message": str(e)}
    except Exception as e:
        return {"success": False, "message": str(e)}


def revise_item_start_price_and_shipping(item_id: str, new_start_price_usd: float) -> dict:
    """
    StartPrice と Shipping Profile を同一 ReviseFixedPriceItem で更新する（片方だけの更新禁止）。
    band は shipping_policy_select.select_shipping_policy のみ。
    """
    from shipping_policy_select import select_shipping_policy

    sel = select_shipping_policy(float(new_start_price_usd))
    price_s = f"{float(new_start_price_usd):.2f}"
    endpoint = ENDPOINTS.get(EBAY_ENV, ENDPOINTS["production"])
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <Item>
    <ItemID>{item_id}</ItemID>
    <StartPrice currencyID="USD">{price_s}</StartPrice>
    <SellerProfiles>
      <SellerShippingProfile>
        <ShippingProfileID>{sel.policy_id}</ShippingProfileID>
      </SellerShippingProfile>
    </SellerProfiles>
  </Item>
</ReviseFixedPriceItemRequest>"""
    try:
        response = trading_post(
            endpoint,
            _make_headers("ReviseFixedPriceItem"),
            xml_body.encode("utf-8"),
            "ReviseFixedPriceItem_price_shipping",
            timeout=30,
        )
        root = ET.fromstring(response.text)
        ns = _NS
        ack = root.find("ns:Ack", ns)
        if ack is not None and ack.text in ("Success", "Warning"):
            logger.info(
                f"✅ eBay Item {item_id} → StartPrice=${price_s} + shipping {sel.policy_name} ({sel.policy_id}) OK"
            )
            return {
                "success": True,
                "message": "price_and_shipping",
                "policy_id": sel.policy_id,
                "policy_name": sel.policy_name,
            }
        longs, codes = _revise_error_messages(root)
        msg = " / ".join(longs) if longs else "Unknown eBay error"
        logger.error(f"❌ revise_item_start_price_and_shipping {item_id}: {msg}")
        return {"success": False, "message": msg}
    except EbayTradingRateLimited as e:
        logger.error("revise_item_start_price_and_shipping: %s", e)
        return {"success": False, "message": str(e)}
    except Exception as e:
        logger.error(f"❌ revise_item_start_price_and_shipping {item_id}: {e}")
        return {"success": False, "message": str(e)}
