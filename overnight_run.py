#!/usr/bin/env python3
"""
overnight_run.py — 夜間バッチ（停止厳禁）
優先順位1: スクレイプ失敗を再試行→出品
優先順位2: リサーチ→出品で出品数最大化
優先順位3: 在庫確認（売り切れ→out of stock維持、購入可能→在庫1復旧）
"""
import sys
import os
import time
import json
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"logs/overnight_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("overnight")

from config import (
    SPREADSHEET_ID, SHEET_NAME, PRIORITY_SHEET_NAME, AUTO_SHEET_NAME,
    AUTO_SHEET_CARD, AUTO_SHEET_HOBBY, AUTO_SHEET_OTHER,
    SLACK_WEBHOOK_URL
)
from sheets_manager import read_active_items, read_all_items, _get_service, update_item_status
from mercari_checker import check_mercari_status
from ebay_updater import set_quantity, mark_out_of_stock
from sold_tracker import is_sold, get_sold_ebay_ids, record_sold
import requests as _requests


def notify_slack(text):
    try:
        _requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
    except:
        pass


def phase1_retry_failed():
    """優先順位1: スクレイプ失敗を全てリセット→再出品"""
    logger.info("=" * 50)
    logger.info("🔧 Phase 1: スクレイプ失敗の再試行")
    logger.info("=" * 50)

    service = _get_service()
    reset_count = 0
    for s_name in [PRIORITY_SHEET_NAME, AUTO_SHEET_NAME, AUTO_SHEET_CARD, AUTO_SHEET_HOBBY, AUTO_SHEET_OTHER]:
        try:
            res = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID, range=f"{s_name}!A2:E500"
            ).execute()
            for i, row in enumerate(res.get("values", [])):
                if len(row) < 5:
                    continue
                st = row[4]
                if "スクレイプ失敗" in st or "出品失敗" in st:
                    update_item_status(i + 2, "", s_name)
                    reset_count += 1
        except:
            pass
    logger.info(f"  {reset_count}件リセット完了")

    if reset_count > 0:
        import fcntl
        lock_file = open("/tmp/auto_lister.lock", "w")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except:
            logger.warning("  auto_lister ロック取得失敗。スキップ。")
            return 0

        from auto_lister import run_auto_listing
        run_auto_listing()
        lock_file.close()

    # 成功件数を集計
    success = 0
    for s_name in [PRIORITY_SHEET_NAME, AUTO_SHEET_NAME, AUTO_SHEET_CARD, AUTO_SHEET_HOBBY, AUTO_SHEET_OTHER]:
        try:
            items = read_active_items(s_name)
            success += sum(1 for i in items if "出品済み" in i.get("status", ""))
        except:
            pass
    return success


def phase2_research_and_list():
    """優先順位2: 全部署リサーチ→出品で出品数最大化"""
    logger.info("=" * 50)
    logger.info("📊 Phase 2: リサーチ→出品")
    logger.info("=" * 50)

    import random
    from auto_sourcer import load_department_keywords, scrape_and_source

    depts = load_department_keywords()
    total_added = 0
    for dept in depts:
        kws = dept["mercari_keywords"]
        dept_name = dept["department"]
        logger.info(f"  ━━━ {dept_name} ({len(kws)}KW) ━━━")
        for kw in kws:
            try:
                scrape_and_source(kw, dept=dept)
            except Exception as e:
                logger.error(f"  Research error ({dept_name}): {e}")
            time.sleep(random.uniform(2, 5))

    # リサーチ結果を出品
    logger.info("  → 出品フェーズ開始")
    import fcntl
    lock_file = open("/tmp/auto_lister.lock", "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except:
        logger.warning("  auto_lister ロック取得失敗。スキップ。")
        return

    from auto_lister import run_auto_listing
    run_auto_listing()
    lock_file.close()


def phase3_inventory_check():
    """優先順位3: 在庫確認。売り切れ→out of stock + SOLD記録。SOLD済みは絶対にリストックしない。"""
    logger.info("=" * 50)
    logger.info("🔍 Phase 3: 在庫確認")
    logger.info("=" * 50)

    items = read_all_items(SHEET_NAME)
    active_items = [
        item for item in items
        if item.get("ebay_item_id") and item.get("mercari_url")
    ]
    logger.info(f"  チェック対象: {len(active_items)}件")

    # SOLD済みIDを一括取得（2重販売防止）
    sold_ids = get_sold_ebay_ids()
    logger.info(f"  SOLD済み: {len(sold_ids)}件（リストック対象外）")

    sold_count = 0
    skipped_sold = 0
    error_count = 0

    for i, item in enumerate(active_items):
        url = item["mercari_url"]
        ebay_id = item["ebay_item_id"]
        status_current = item.get("status", "")

        if i > 0 and i % 100 == 0:
            logger.info(f"  進捗: {i}/{len(active_items)} (売切:{sold_count})")

        # SOLD済み商品はスキップ
        if ebay_id in sold_ids:
            skipped_sold += 1
            continue

        result = check_mercari_status(url, delay=1.0)
        m_status = result.get("status", "")

        if m_status in ("sold_out", "deleted"):
            if "active" in status_current.lower():
                mark_out_of_stock(ebay_id)
                try:
                    record_sold(mercari_url=url, ebay_item_id=ebay_id)
                except Exception as e:
                    logger.error(f"  SOLD記録失敗: {e}")
                sold_count += 1
        elif m_status == "auction":
            if "active" in status_current.lower():
                mark_out_of_stock(ebay_id)
                sold_count += 1
                logger.warning(f"  ⛔ オークション変更→在庫0: {ebay_id}")
        # active商品の在庫1復旧は絶対に行わない（2重販売の原因）
        elif m_status == "error":
            error_count += 1

    logger.info(f"  在庫確認完了: 売切/オークション→終了:{sold_count} / SOLD skip:{skipped_sold} / エラー:{error_count}")
    return sold_count, 0


def get_active_count():
    """eBayアクティブ出品数を取得"""
    import xml.etree.ElementTree as ET
    from config import EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID
    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "GetMyeBaySelling",
        "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml",
    }
    xml = f'<?xml version="1.0"?><GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents"><RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials><ActiveList><Include>true</Include><Pagination><EntriesPerPage>1</EntriesPerPage></Pagination></ActiveList></GetMyeBaySellingRequest>'
    try:
        resp = _requests.post("https://api.ebay.com/ws/api.dll", headers=headers, data=xml.encode("utf-8"), timeout=30)
        root = ET.fromstring(resp.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
        t = root.find(".//ns:ActiveList/ns:PaginationResult/ns:TotalNumberOfEntries", ns)
        return int(t.text) if t is not None else 0
    except:
        return 0


if __name__ == "__main__":
    # ========== test_rules.py ゲート ==========
    import subprocess
    test_result = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(__file__), "test_rules.py")],
        capture_output=True, text=True, timeout=120
    )
    if test_result.returncode != 0:
        logger.error("🚨 test_rules.py 失敗 — バッチを中止")
        logger.error(test_result.stdout)
        notify_slack("🚨 test_rules.py 失敗 — 夜間バッチ中止")
        sys.exit(1)
    logger.info("✅ test_rules.py 全テスト合格")
    # ==========================================

    start_time = datetime.now()
    start_count = get_active_count()
    logger.info(f"🌙 夜間バッチ開始 | 開始時アクティブ: {start_count}件 | 目標: 1,100件")
    notify_slack(f"🌙 夜間バッチ開始 | アクティブ: {start_count}件")

    # Phase 1: スクレイプ失敗の再試行
    try:
        phase1_retry_failed()
    except Exception as e:
        logger.error(f"Phase 1 エラー: {e}")

    count_after_p1 = get_active_count()
    logger.info(f"📊 Phase 1 完了 | アクティブ: {count_after_p1}件 (+{count_after_p1 - start_count})")

    # Phase 2: リサーチ→出品
    try:
        phase2_research_and_list()
    except Exception as e:
        logger.error(f"Phase 2 エラー: {e}")

    count_after_p2 = get_active_count()
    logger.info(f"📊 Phase 2 完了 | アクティブ: {count_after_p2}件 (+{count_after_p2 - count_after_p1})")

    # Phase 3: 在庫確認
    try:
        phase3_inventory_check()
    except Exception as e:
        logger.error(f"Phase 3 エラー: {e}")

    # 最終レポート
    end_count = get_active_count()
    elapsed = (datetime.now() - start_time).total_seconds() / 3600
    report = (
        f"🌅 夜間バッチ完了\n"
        f"開始: {start_count}件 → 終了: {end_count}件 (+{end_count - start_count})\n"
        f"所要時間: {elapsed:.1f}時間"
    )
    logger.info(report)
    notify_slack(report)
