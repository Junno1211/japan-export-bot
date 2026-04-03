#!/usr/bin/env python3
"""
restore_stock.py — 緊急復旧スクリプト

2026-03-31のオークション誤検出により在庫0にされた554件を復旧する。
在庫管理表にはもう存在しないため、eBay GetItem APIでSKU（メルカリURL）を直接取得し、
メルカリの状態を確認して購入可能な商品のみ在庫を1に戻す。
"""

import sys
import os
import logging
import time
import xml.etree.ElementTree as ET
import requests
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import (
    EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID,
    EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV
)
from mercari_checker import check_mercari_status
from ebay_updater import set_quantity

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            f"logs/restore_{datetime.now().strftime('%Y%m%d_%H%M')}.log",
            encoding="utf-8"
        )
    ]
)
logger = logging.getLogger(__name__)

ENDPOINTS = {
    "production": "https://api.ebay.com/ws/api.dll",
    "sandbox":    "https://api.sandbox.ebay.com/ws/api.dll"
}


def load_false_positive_ids() -> list:
    """ログから誤検出されたeBay ItemIDを抽出"""
    ids = set()
    log_path = os.path.join(os.path.dirname(__file__), "logs", "monitor_20260331.log")
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            if "在庫0に更新完了(オークション)" in line:
                parts = line.strip().split("完了(オークション): ")
                if len(parts) == 2:
                    ids.add(parts[1].strip())
    return sorted(ids)


def get_ebay_item_sku(item_id: str) -> dict:
    """eBay GetItem APIでSKU（メルカリURL）とリスティング状態を取得"""
    endpoint = ENDPOINTS.get(EBAY_ENV, ENDPOINTS["production"])
    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "GetItem",
        "X-EBAY-API-SITEID": EBAY_SITE_ID,
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml",
    }
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <DetailLevel>ReturnAll</DetailLevel>
</GetItemRequest>"""

    try:
        resp = requests.post(endpoint, headers=headers, data=xml_body.encode("utf-8"), timeout=30)
        root = ET.fromstring(resp.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}

        ack = root.find("ns:Ack", ns)
        if ack is not None and ack.text in ("Success", "Warning"):
            sku_el = root.find(".//ns:SKU", ns)
            qty_el = root.find(".//ns:Quantity", ns)
            status_el = root.find(".//ns:ListingStatus", ns)
            title_el = root.find(".//ns:Title", ns)
            return {
                "success": True,
                "sku": sku_el.text if sku_el is not None else "",
                "quantity": int(qty_el.text) if qty_el is not None else -1,
                "listing_status": status_el.text if status_el is not None else "Unknown",
                "title": title_el.text if title_el is not None else "",
            }
        else:
            errors = root.findall(".//ns:Errors", ns)
            msg = " / ".join([e.find("ns:LongMessage", ns).text for e in errors if e.find("ns:LongMessage", ns) is not None])
            return {"success": False, "sku": "", "quantity": -1, "listing_status": "Error", "title": "", "error": msg}
    except Exception as e:
        return {"success": False, "sku": "", "quantity": -1, "listing_status": "Error", "title": "", "error": str(e)}


def main(dry_run=False):
    start = datetime.now()
    logger.info("=" * 60)
    logger.info("緊急復旧: オークション誤検出による在庫0を復旧")
    if dry_run:
        logger.info("DRY RUN モード（eBay更新はしない）")
    logger.info("=" * 60)

    false_positive_ids = load_false_positive_ids()
    logger.info(f"誤検出ItemID: {len(false_positive_ids)}件")

    restored = 0
    kept_zero = 0
    already_ended = 0
    no_sku = 0
    errors = 0
    auction_real = 0

    for i, ebay_id in enumerate(false_positive_ids):
        if i > 0 and i % 50 == 0:
            logger.info(f"--- 進捗: {i}/{len(false_positive_ids)} (復旧:{restored} / 維持:{kept_zero} / 終了済:{already_ended} / エラー:{errors}) ---")

        # eBay APIでSKU取得
        ebay_info = get_ebay_item_sku(ebay_id)
        if not ebay_info["success"]:
            logger.warning(f"  [{i+1}] {ebay_id}: eBay API失敗: {ebay_info.get('error', '')[:60]}")
            errors += 1
            continue

        # 既にEndedなら復旧不要
        if ebay_info["listing_status"] == "Ended":
            already_ended += 1
            continue

        sku = ebay_info.get("sku", "")
        title = ebay_info.get("title", "")

        # SKUがメルカリURLでなければスキップ
        if not sku or "mercari" not in sku:
            logger.warning(f"  [{i+1}] {ebay_id}: SKUなし/非メルカリ (SKU={sku[:40]}) → 在庫1に復旧（メルカリ確認不可）")
            if not dry_run:
                res = set_quantity(ebay_id, 1)
                if res["success"]:
                    restored += 1
                else:
                    logger.error(f"    復旧失敗: {res['message']}")
                    errors += 1
            else:
                restored += 1
            continue

        # メルカリ状態チェック
        mc = check_mercari_status(sku, delay=1.0)
        mc_status = mc.get("status", "error")

        if mc_status == "active":
            if not dry_run:
                res = set_quantity(ebay_id, 1)
                if res["success"]:
                    logger.info(f"  [{i+1}] {ebay_id} → 在庫1に復旧: {title[:40]}")
                    restored += 1
                else:
                    logger.error(f"  [{i+1}] {ebay_id} 復旧失敗: {res['message']}")
                    errors += 1
            else:
                logger.info(f"  [DRY] [{i+1}] {ebay_id} → 在庫1に復旧予定: {title[:40]}")
                restored += 1

        elif mc_status == "auction":
            logger.info(f"  [{i+1}] {ebay_id} → 本当のオークション。在庫0維持")
            kept_zero += 1
            auction_real += 1

        elif mc_status in ("sold_out", "deleted"):
            logger.info(f"  [{i+1}] {ebay_id} → 売切/削除。在庫0維持")
            kept_zero += 1

        elif mc_status == "error":
            # エラー時は安全のため在庫1に戻す（偽陽性の被害を最小化）
            logger.warning(f"  [{i+1}] {ebay_id} → メルカリ確認エラー → 安全のため在庫1に復旧: {mc.get('error', '')[:40]}")
            if not dry_run:
                res = set_quantity(ebay_id, 1)
                if res["success"]:
                    restored += 1
                else:
                    errors += 1
            else:
                restored += 1

        # eBay APIレート制限対策
        time.sleep(0.3)

    elapsed = (datetime.now() - start).seconds

    logger.info("")
    logger.info("=" * 60)
    logger.info("復旧結果サマリー")
    logger.info("=" * 60)
    logger.info(f"  対象: {len(false_positive_ids)}件")
    logger.info(f"  在庫1に復旧: {restored}件")
    logger.info(f"  在庫0維持（売切/オークション）: {kept_zero}件（うちオークション: {auction_real}件）")
    logger.info(f"  既にEnded: {already_ended}件")
    logger.info(f"  SKUなし復旧: {no_sku}件")
    logger.info(f"  エラー: {errors}件")
    logger.info(f"  所要時間: {elapsed}秒")
    logger.info("=" * 60)

    # Slack通知
    try:
        from config import SLACK_WEBHOOK_URL_ORDERS
        if SLACK_WEBHOOK_URL_ORDERS:
            msg = f"復旧完了: 在庫1に{restored}件 / 在庫0維持{kept_zero}件 / Ended{already_ended}件 / エラー{errors}件"
            requests.post(SLACK_WEBHOOK_URL_ORDERS, json={"text": msg}, timeout=10)
    except:
        pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="eBay更新せずにテスト実行")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
