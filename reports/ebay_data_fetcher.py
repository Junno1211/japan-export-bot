"""
eBay Trading API GetOrders で完了済み注文（売上）を取得する。

認証は config を import のみ（config.py 自体は変更しない）。
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import requests
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)

_NS = {"ns": "urn:ebay:apis:eBLBaseComponents"}


@dataclass(frozen=True)
class SoldLine:
    """1 取引行（Completed / Checkout Complete）。"""

    order_id: str
    item_id: str
    title: str
    price_usd: float
    sku: str


def _endpoint() -> str:
    from config import EBAY_ENV

    if (EBAY_ENV or "").lower() == "sandbox":
        return "https://api.sandbox.ebay.com/ws/api.dll"
    return "https://api.ebay.com/ws/api.dll"


def _headers(call_name: str) -> dict[str, str]:
    from config import (
        EBAY_APP_ID,
        EBAY_CERT_ID,
        EBAY_DEV_ID,
        EBAY_SITE_ID,
    )

    return {
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": call_name,
        "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml",
    }


def _ebay_ts(dt: datetime) -> str:
    """UTC の eBay ISO 形式（ミリ秒付き）。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def parse_get_orders_response(xml_text: str) -> tuple[list[SoldLine], bool]:
    """
    GetOrders 応答 XML を解析する。

    Returns:
        (sold_lines, has_more_orders)
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error("GetOrders XML parse error: %s", e)
        return [], False

    ack = root.find("ns:Ack", _NS)
    if ack is None or (ack.text or "") not in ("Success", "Warning"):
        logger.error("GetOrders Ack failure: %s", xml_text[:500])
        return [], False

    has_more_el = root.find("ns:HasMoreOrders", _NS)
    has_more = (has_more_el is not None and (has_more_el.text or "").lower() == "true")

    out: list[SoldLine] = []
    order_array = root.find("ns:OrderArray", _NS)
    if order_array is None:
        return out, has_more

    for order in order_array.findall("ns:Order", _NS):
        status = order.find("ns:OrderStatus", _NS)
        if status is None or status.text != "Completed":
            continue
        checkout = order.find("ns:CheckoutStatus/ns:Status", _NS)
        if checkout is None or checkout.text != "Complete":
            continue
        oid_el = order.find("ns:OrderID", _NS)
        order_id = (oid_el.text or "").strip() if oid_el is not None else ""
        transactions = order.findall("ns:TransactionArray/ns:Transaction", _NS)
        for t in transactions:
            item = t.find("ns:Item", _NS)
            item_id = ""
            title = ""
            sku = ""
            if item is not None:
                iid = item.find("ns:ItemID", _NS)
                if iid is not None and iid.text:
                    item_id = iid.text.strip()
                tit = item.find("ns:Title", _NS)
                if tit is not None and tit.text:
                    title = tit.text.strip()
                sk = item.find("ns:SKU", _NS)
                if sk is not None and sk.text:
                    sku = sk.text.strip()
            price_el = t.find("ns:TransactionPrice", _NS)
            raw_price = (price_el.text or "0").strip() if price_el is not None else "0"
            try:
                price_usd = float(raw_price)
            except ValueError:
                price_usd = 0.0
            out.append(
                SoldLine(
                    order_id=order_id,
                    item_id=item_id,
                    title=title,
                    price_usd=price_usd,
                    sku=sku,
                )
            )
    return out, has_more


def fetch_completed_orders(
    time_from_utc: datetime,
    time_to_utc: datetime,
    *,
    post: Callable[..., Any] | None = None,
    max_pages: int = 40,
    entries_per_page: int = 100,
    sleep_sec: float = 0.35,
) -> list[SoldLine]:
    """
    CreateTimeFrom / To の範囲で Completed かつ Checkout Complete の取引を取得（ページング）。

    post: テスト用に差し替え可能（既定は requests.post）。
    """
    from config import EBAY_AUTH_TOKEN

    post_fn = post or requests.post
    endpoint = _endpoint()
    headers = _headers("GetOrders")

    all_rows: list[SoldLine] = []
    page = 1
    while page <= max_pages:
        xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetOrdersRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <CreateTimeFrom>{_ebay_ts(time_from_utc)}</CreateTimeFrom>
  <CreateTimeTo>{_ebay_ts(time_to_utc)}</CreateTimeTo>
  <OrderRole>Seller</OrderRole>
  <OrderStatus>Completed</OrderStatus>
  <Pagination>
    <EntriesPerPage>{entries_per_page}</EntriesPerPage>
    <PageNumber>{page}</PageNumber>
  </Pagination>
</GetOrdersRequest>"""

        last_exc: Exception | None = None
        resp = None
        for attempt in range(3):
            try:
                resp = post_fn(
                    endpoint,
                    headers=headers,
                    data=xml_body.encode("utf-8"),
                    timeout=60,
                )
                break
            except RequestException as e:
                last_exc = e
                logger.warning("GetOrders HTTP fail attempt %s: %s", attempt + 1, e)
                time.sleep(1.0 * (attempt + 1))
        if resp is None:
            logger.error("GetOrders リクエスト失敗: %s", last_exc)
            break

        rows, has_more = parse_get_orders_response(resp.text)
        all_rows.extend(rows)
        if not has_more or not rows:
            break
        page += 1
        time.sleep(sleep_sec)

    return all_rows
