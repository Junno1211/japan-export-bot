#!/usr/bin/env python3
"""
mass_restore.py — 大量リスティング復元スクリプト

Phase 1: eBay ActiveListからquantity=0を全件取得し、一括でquantity=1に復元
Phase 2: EndedListから最近終了したアイテムをRelistFixedPriceItemで再出品
Phase 3: 復元結果のサマリーをSlack通知

使い方:
    python3 mass_restore.py              # Phase 1 + 2 実行
    python3 mass_restore.py --phase1     # ActiveList復元のみ
    python3 mass_restore.py --phase2     # Relist（終了アイテム再出品）のみ
    python3 mass_restore.py --dry-run    # 確認のみ（実行しない）
    python3 mass_restore.py --count      # 現在のActive件数を確認
"""

import sys
import logging
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

from config import (
    EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID,
    EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV,
    SLACK_WEBHOOK_URL
)
from sold_tracker import get_sold_ebay_ids

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/mass_restore.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)

EBAY_ENDPOINT = {
    "production": "https://api.ebay.com/ws/api.dll",
    "sandbox":    "https://api.sandbox.ebay.com/ws/api.dll"
}.get(EBAY_ENV, "https://api.ebay.com/ws/api.dll")

HEADERS_BASE = {
    "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
    "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
    "X-EBAY-API-APP-NAME": EBAY_APP_ID,
    "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
    "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
    "Content-Type": "text/xml",
}


def notify_slack(text: str):
    if SLACK_WEBHOOK_URL:
        try:
            requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
        except:
            pass


def _headers(call_name: str) -> dict:
    h = dict(HEADERS_BASE)
    h["X-EBAY-API-CALL-NAME"] = call_name
    return h


# ============================================================
#  eBay API呼び出し
# ============================================================

def get_active_count() -> int:
    """現在のアクティブリスティング件数を取得"""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <ActiveList>
    <Include>true</Include>
    <Pagination><EntriesPerPage>1</EntriesPerPage><PageNumber>1</PageNumber></Pagination>
  </ActiveList>
</GetMyeBaySellingRequest>"""
    try:
        resp = requests.post(EBAY_ENDPOINT, headers=_headers("GetMyeBaySelling"),
                             data=xml.encode("utf-8"), timeout=30)
        root = ET.fromstring(resp.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
        total = root.find(".//ns:ActiveList/ns:PaginationResult/ns:TotalNumberOfEntries", ns)
        return int(total.text) if total is not None else -1
    except Exception as e:
        logger.error(f"Active count取得失敗: {e}")
        return -1


def get_all_active_items() -> list:
    """ActiveListの全アイテムを取得（ページング対応）"""
    all_items = []
    for page in range(1, 20):  # 最大200*19=3800件
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <ActiveList>
    <Include>true</Include>
    <Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>
  </ActiveList>
  <DetailLevel>ReturnAll</DetailLevel>
</GetMyeBaySellingRequest>"""
        try:
            resp = requests.post(EBAY_ENDPOINT, headers=_headers("GetMyeBaySelling"),
                                 data=xml.encode("utf-8"), timeout=60)
            root = ET.fromstring(resp.text)
            ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
            items = root.findall(".//ns:ActiveList//ns:Item", ns)
            if not items:
                break
            for item_el in items:
                ebay_id = item_el.find("ns:ItemID", ns)
                sku_el = item_el.find("ns:SKU", ns)
                qty_el = item_el.find("ns:QuantityAvailable", ns)
                if qty_el is None:
                    qty_el = item_el.find("ns:Quantity", ns)
                all_items.append({
                    "ebay_id": ebay_id.text if ebay_id is not None else "",
                    "sku": sku_el.text if sku_el is not None else "",
                    "quantity": int(qty_el.text) if qty_el is not None else -1,
                })
            # ページング終了チェック
            total_pages = root.find(".//ns:ActiveList/ns:PaginationResult/ns:TotalNumberOfPages", ns)
            if total_pages is not None and page >= int(total_pages.text):
                break
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"ActiveList page {page} 取得失敗: {e}")
            break
    return all_items


def get_ended_items(days_back: int = 3) -> list:
    """最近終了したアイテムを取得"""
    all_items = []
    for page in range(1, 20):
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <UnsoldList>
    <Include>true</Include>
    <Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>
    <DurationInDays>{days_back}</DurationInDays>
  </UnsoldList>
  <DetailLevel>ReturnAll</DetailLevel>
</GetMyeBaySellingRequest>"""
        try:
            resp = requests.post(EBAY_ENDPOINT, headers=_headers("GetMyeBaySelling"),
                                 data=xml.encode("utf-8"), timeout=60)
            root = ET.fromstring(resp.text)
            ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
            items = root.findall(".//ns:UnsoldList//ns:Item", ns)
            if not items:
                break
            for item_el in items:
                ebay_id = item_el.find("ns:ItemID", ns)
                sku_el = item_el.find("ns:SKU", ns)
                title_el = item_el.find("ns:Title", ns)
                all_items.append({
                    "ebay_id": ebay_id.text if ebay_id is not None else "",
                    "sku": sku_el.text if sku_el is not None else "",
                    "title": title_el.text if title_el is not None else "",
                })
            total_pages = root.find(".//ns:UnsoldList/ns:PaginationResult/ns:TotalNumberOfPages", ns)
            if total_pages is not None and page >= int(total_pages.text):
                break
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"UnsoldList page {page} 取得失敗: {e}")
            break
    return all_items


def set_quantity(item_id: str, quantity: int) -> dict:
    """ReviseInventoryStatusで数量変更"""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseInventoryStatusRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <InventoryStatus>
    <ItemID>{item_id}</ItemID>
    <Quantity>{quantity}</Quantity>
  </InventoryStatus>
</ReviseInventoryStatusRequest>"""
    try:
        resp = requests.post(EBAY_ENDPOINT, headers=_headers("ReviseInventoryStatus"),
                             data=xml.encode("utf-8"), timeout=30)
        root = ET.fromstring(resp.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
        ack = root.find("ns:Ack", ns)
        if ack is not None and ack.text in ("Success", "Warning"):
            return {"success": True}
        errs = [e.text for e in root.findall(".//ns:LongMessage", ns)]
        return {"success": False, "errors": errs}
    except Exception as e:
        return {"success": False, "errors": [str(e)]}


def relist_item(item_id: str) -> dict:
    """RelistFixedPriceItemで終了アイテムを再出品"""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<RelistFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <Item>
    <ItemID>{item_id}</ItemID>
  </Item>
</RelistFixedPriceItemRequest>"""
    try:
        resp = requests.post(EBAY_ENDPOINT, headers=_headers("RelistFixedPriceItem"),
                             data=xml.encode("utf-8"), timeout=30)
        root = ET.fromstring(resp.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
        ack = root.find("ns:Ack", ns)
        new_id = root.find(".//ns:ItemID", ns)
        if ack is not None and ack.text in ("Success", "Warning"):
            return {"success": True, "new_item_id": new_id.text if new_id is not None else item_id}
        errs = [e.text for e in root.findall(".//ns:LongMessage", ns)]
        return {"success": False, "errors": errs}
    except Exception as e:
        return {"success": False, "errors": [str(e)]}


# ============================================================
#  Phase 1: ActiveListのquantity=0を全復元
# ============================================================

def phase1_restore_oos(dry_run: bool = False) -> dict:
    """ActiveListで在庫0のアイテムをquantity=1に復元"""
    logger.info("=" * 60)
    logger.info("Phase 1: ActiveList OOS → quantity=1 復元")
    logger.info("=" * 60)

    sold_ids = get_sold_ebay_ids()
    logger.info(f"SOLD済み: {len(sold_ids)}件（リストック対象外）")

    all_items = get_all_active_items()
    logger.info(f"ActiveList全件: {len(all_items)}件")

    oos_items = [i for i in all_items if i["quantity"] == 0]
    logger.info(f"うち quantity=0: {len(oos_items)}件")

    restored = 0
    failed = 0
    skipped_sold = 0
    errors_log = []

    for idx, item in enumerate(oos_items):
        ebay_id = item["ebay_id"]

        # SOLD済み商品は絶対にリストックしない
        if ebay_id in sold_ids:
            skipped_sold += 1
            continue

        if dry_run:
            logger.info(f"  [DRY RUN] {idx+1}/{len(oos_items)} — {ebay_id} → quantity=1")
            restored += 1
            continue

        result = set_quantity(ebay_id, 1)
        if result["success"]:
            restored += 1
            if restored % 50 == 0:
                logger.info(f"  進捗: {restored}/{len(oos_items)} 復元完了")
        else:
            failed += 1
            err_msg = " / ".join(result.get("errors", ["unknown"]))
            errors_log.append(f"{ebay_id}: {err_msg}")
            logger.warning(f"  復元失敗 {ebay_id}: {err_msg}")

        # レート制限対策
        if (idx + 1) % 20 == 0:
            time.sleep(1)

    logger.info(f"Phase 1 完了: 復元 {restored}件 / 失敗 {failed}件")
    return {"restored": restored, "failed": failed, "errors": errors_log}


# ============================================================
#  Phase 2: EndedListからRelist
# ============================================================

def phase2_relist_ended(dry_run: bool = False) -> dict:
    """最近終了したアイテムをRelistFixedPriceItemで再出品"""
    logger.info("=" * 60)
    logger.info("Phase 2: Ended → RelistFixedPriceItem")
    logger.info("=" * 60)

    ended_items = get_ended_items(days_back=3)
    logger.info(f"最近終了したアイテム: {len(ended_items)}件")

    relisted = 0
    failed = 0
    errors_log = []

    for idx, item in enumerate(ended_items):
        ebay_id = item["ebay_id"]
        title = item.get("title", "")[:40]

        if dry_run:
            logger.info(f"  [DRY RUN] {idx+1}/{len(ended_items)} — {ebay_id} ({title})")
            relisted += 1
            continue

        result = relist_item(ebay_id)
        if result["success"]:
            relisted += 1
            new_id = result.get("new_item_id", "")
            logger.info(f"  Relist成功 {ebay_id} → {new_id} ({title})")
            if relisted % 50 == 0:
                logger.info(f"  進捗: {relisted}/{len(ended_items)} relist完了")
        else:
            failed += 1
            err_msg = " / ".join(result.get("errors", ["unknown"]))
            errors_log.append(f"{ebay_id}: {err_msg}")
            # Relistできないアイテムは無視して次へ
            logger.warning(f"  Relist失敗 {ebay_id}: {err_msg[:80]}")

        # レート制限対策
        if (idx + 1) % 10 == 0:
            time.sleep(1)

    logger.info(f"Phase 2 完了: Relist {relisted}件 / 失敗 {failed}件")
    return {"relisted": relisted, "failed": failed, "errors": errors_log}


# ============================================================
#  メイン
# ============================================================

def run_full_restore(dry_run: bool = False, phase1: bool = True, phase2: bool = True):
    start = datetime.now()
    logger.info(f"{'='*60}")
    logger.info(f"大量復元開始 — {start.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"{'='*60}")

    # 復元前のアクティブ件数
    before_count = get_active_count()
    logger.info(f"復元前 Active件数: {before_count}")
    notify_slack(f"大量復元開始 | 現在Active: {before_count}件 | 目標: 1100件")

    p1_result = {"restored": 0, "failed": 0}
    p2_result = {"relisted": 0, "failed": 0}

    if phase1:
        p1_result = phase1_restore_oos(dry_run=dry_run)

    if phase2:
        p2_result = phase2_relist_ended(dry_run=dry_run)

    # 復元後のアクティブ件数
    time.sleep(3)
    after_count = get_active_count()

    elapsed = (datetime.now() - start).total_seconds()
    summary = (
        f"大量復元完了 ({elapsed:.0f}秒)\n"
        f"Phase1 (OOS復元): {p1_result['restored']}件成功 / {p1_result['failed']}件失敗\n"
        f"Phase2 (Relist): {p2_result['relisted']}件成功 / {p2_result['failed']}件失敗\n"
        f"Active件数: {before_count} → {after_count}"
    )
    logger.info(summary)
    notify_slack(summary)

    # 不足分の計算
    target = 1100
    gap = target - after_count
    if gap > 0:
        gap_msg = f"目標1100件まであと{gap}件 — 新規出品が必要"
        logger.info(gap_msg)
        notify_slack(gap_msg)

    return {
        "before": before_count,
        "after": after_count,
        "phase1": p1_result,
        "phase2": p2_result,
        "gap": max(0, target - after_count),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="eBay大量リスティング復元")
    parser.add_argument("--dry-run", action="store_true", help="確認のみ（実行しない）")
    parser.add_argument("--phase1", action="store_true", help="Phase1のみ")
    parser.add_argument("--phase2", action="store_true", help="Phase2のみ")
    parser.add_argument("--count", action="store_true", help="Active件数確認のみ")
    args = parser.parse_args()

    import os
    os.makedirs("logs", exist_ok=True)

    if args.count:
        count = get_active_count()
        print(f"現在のActive件数: {count}")
        sys.exit(0)

    # --phase1/--phase2 指定なしなら両方実行
    do_p1 = args.phase1 or (not args.phase1 and not args.phase2)
    do_p2 = args.phase2 or (not args.phase1 and not args.phase2)

    result = run_full_restore(dry_run=args.dry_run, phase1=do_p1, phase2=do_p2)

    if result["gap"] > 0:
        print(f"\n残り{result['gap']}件は新規リサーチ・出品が必要です。")
        print("実行: python3 auto_sourcer.py && python3 auto_lister.py")
