#!/usr/bin/env python3
"""
inventory_manager.py — 在庫管理部
無在庫転売の生命線。メルカリ在庫を定期チェックし、
売り切れ商品のeBay出品を即時終了してDefectを防止する。

機能:
1. 全アクティブ出品のメルカリ在庫チェック
2. 売り切れ検知→eBay在庫0→シート更新→Slack通知
3. オークション変更検知→eBay在庫0（仕入れ不可のため）
4. 在庫サマリーレポート
"""

import sys
import os
import logging
import time
import fcntl
import requests
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import (
    SPREADSHEET_ID, SHEET_NAME, COL_STATUS, COL_EBAY_ITEM_ID, COL_MERCARI_URL,
    SLACK_WEBHOOK_URL_ORDERS
)
from sheets_manager import read_all_items, _get_service
from mercari_checker import check_mercari_status
from ebay_updater import mark_out_of_stock
from sold_tracker import record_sold

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "logs",
                         f"inventory_{datetime.now().strftime('%Y%m%d')}.log"),
            encoding="utf-8"
        )
    ]
)
logger = logging.getLogger(__name__)

LOCK_FILE = "/tmp/inventory_manager.lock"


def notify_slack(text: str):
    try:
        requests.post(SLACK_WEBHOOK_URL_ORDERS, json={"text": text}, timeout=10)
    except Exception as e:
        logger.warning(f"Slack通知失敗: {e}")


def run_inventory_check():
    """全アクティブ出品のメルカリ在庫を確認し、売り切れをeBayから即時撤去する"""
    # 二重起動防止
    lock_file = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.info("別の在庫チェックが実行中。スキップ。")
        return

    start = datetime.now()
    logger.info("=" * 50)
    logger.info("🔄 在庫管理部 — 在庫チェック開始")
    logger.info("=" * 50)

    # 在庫管理表からアクティブ商品を取得
    try:
        items = read_all_items(SHEET_NAME)
    except Exception as e:
        logger.error(f"在庫管理表の読み込み失敗: {e}")
        notify_slack(f"🚨 在庫管理: シート読み込み失敗 — {e}")
        return

    active_items = [
        item for item in items
        if item.get("status", "").lower() == "active"
        and item.get("mercari_url")
        and item.get("ebay_item_id")
    ]
    logger.info(f"チェック対象: {len(active_items)}件")

    if not active_items:
        logger.info("対象なし。終了。")
        return

    service = _get_service()
    sold_out_count = 0
    auction_count = 0
    error_count = 0
    status_col = chr(65 + COL_STATUS)  # F

    for i, item in enumerate(active_items):
        url = item["mercari_url"]
        ebay_id = item["ebay_item_id"]
        row = item["row"]

        if i > 0 and i % 50 == 0:
            logger.info(f"--- 進捗: {i}/{len(active_items)} ---")

        # ステップ1: APIチェック
        result = check_mercari_status(url, delay=1.5)
        status = result.get("status", "")

        # ステップ2: sold_out/deleted → 即座にeBay在庫0
        if status in ("sold_out", "deleted"):
            sold_out_count += 1
            logger.warning(f"⛔ 売り切れ: {url} → eBay {ebay_id}")
            ebay_res = mark_out_of_stock(ebay_id)
            if ebay_res["success"]:
                logger.info(f"  ✅ eBay在庫0完了: {ebay_id}")
            else:
                logger.error(f"  ❌ eBay更新失敗: {ebay_res['message']}")
            try:
                record_sold(mercari_url=url, ebay_item_id=ebay_id)
            except Exception as e:
                logger.error(f"  SOLD記録失敗: {e}")
            try:
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"{SHEET_NAME}!{status_col}{row}",
                    valueInputOption="USER_ENTERED",
                    body={"values": [["ENDED_売切"]]}
                ).execute()
            except Exception as e:
                logger.error(f"  シート更新失敗: {e}")

        # ステップ3: auction → 即座にeBay在庫0
        elif status == "auction":
            auction_count += 1
            logger.warning(f"⛔ オークション変更検出: {url} → eBay {ebay_id}")
            ebay_res = mark_out_of_stock(ebay_id)
            if ebay_res["success"]:
                logger.info(f"  ✅ eBay在庫0完了(オークション): {ebay_id}")
            else:
                logger.error(f"  ❌ eBay更新失敗(オークション): {ebay_res['message']}")
            try:
                service.spreadsheets().values().update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"{SHEET_NAME}!{status_col}{row}",
                    valueInputOption="USER_ENTERED",
                    body={"values": [["ENDED_オークション"]]}
                ).execute()
            except Exception as e:
                logger.error(f"  シート更新失敗: {e}")

        # ステップ4-6: active → 「購入手続きへ」ボタンをHTML確認
        elif status == "active":
            from mercari_checker import _check_by_html
            html_result = _check_by_html(url)
            html_status = html_result.get("status", "")
            # ステップ5: ボタンなし → eBay在庫0
            if html_status != "active":
                sold_out_count += 1
                logger.warning(f"⛔ 購入手続きボタンなし: {url} → eBay {ebay_id}")
                ebay_res = mark_out_of_stock(ebay_id)
                if ebay_res["success"]:
                    logger.info(f"  ✅ eBay在庫0完了(ボタンなし): {ebay_id}")
                else:
                    logger.error(f"  ❌ eBay更新失敗: {ebay_res['message']}")
                try:
                    service.spreadsheets().values().update(
                        spreadsheetId=SPREADSHEET_ID,
                        range=f"{SHEET_NAME}!{status_col}{row}",
                        valueInputOption="USER_ENTERED",
                        body={"values": [["ENDED_購入不可"]]}
                    ).execute()
                except Exception as e:
                    logger.error(f"  シート更新失敗: {e}")
            # ステップ6: ボタンあり → 在庫あり（何もしない）

        elif status == "error":
            error_count += 1

    elapsed = (datetime.now() - start).seconds

    # サマリーレポート
    summary = (
        f"在庫チェック完了: {len(active_items)}件\n"
        f"売り切れ終了: {sold_out_count}件\n"
        f"エラー: {error_count}件\n"
        f"所要時間: {elapsed}秒"
    )
    logger.info(f"\n{summary}")

    # 売り切れが発生した場合のみSlack通知
    if sold_out_count > 0:
        notify_slack(f"在庫チェック: {sold_out_count}件売り切れ→eBay終了済 / 残アクティブ{len(active_items) - sold_out_count}件")


def load_sold_urls() -> set:
    """items.csvからSOLD記録済みURLを全て読み込む"""
    import csv
    sold = set()
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "items.csv")
    if not os.path.exists(csv_path):
        return sold
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for key in ("SOLD_URL", "mercari_url"):
                url = row.get(key, "").strip()
                if url:
                    sold.add(url)
    return sold


def safe_restock(ebay_item_id: str, mercari_url: str) -> dict:
    """
    安全な在庫復旧。以下を全てチェックしてからのみ復旧する:
    1. SOLD_URLに含まれていないこと（売れた商品は二度と戻さない）
    2. check_mercari_statusでstatus="active"であること（「購入手続きへ」ボタン確認）
    """
    from ebay_updater import set_quantity as _set_qty

    if not ebay_item_id or not mercari_url:
        return {"success": False, "reason": "ID or URL missing"}

    # 1. SOLD_URL確認
    sold_urls = load_sold_urls()
    if mercari_url in sold_urls:
        logger.warning(f"⛔ SOLD_URL: {mercari_url} → 復旧禁止")
        return {"success": False, "reason": "SOLD_URL"}

    # 2. メルカリ在庫確認（「購入手続きへ」ボタン判定）
    result = check_mercari_status(mercari_url, delay=1.0)
    status = result.get("status", "")

    if status != "active":
        logger.warning(f"⛔ メルカリ {status}: {mercari_url} → 復旧禁止")
        return {"success": False, "reason": f"mercari_{status}"}

    # 3. eBay在庫を1に戻す
    res = _set_qty(ebay_item_id, 1)
    if res["success"]:
        logger.info(f"✅ 復旧: {ebay_item_id} ← {mercari_url}")
    return res


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="10分間隔で常時チェック")
    parser.add_argument("--interval", type=int, default=600, help="ループ間隔（秒）デフォルト600=10分")
    args = parser.parse_args()

    os.makedirs(os.path.join(os.path.dirname(__file__), "logs"), exist_ok=True)

    if args.loop:
        logger.info(f"🔁 在庫管理部 常駐モード（間隔: {args.interval}秒）")
        while True:
            try:
                run_inventory_check()
            except Exception as e:
                logger.error(f"在庫チェックエラー（継続）: {e}")
            time.sleep(args.interval)
    else:
        run_inventory_check()
