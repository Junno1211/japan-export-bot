#!/usr/bin/env python3
"""
test_rules.py — 出品前ルールチェック（cron前に毎回実行）
1つでも失敗したら処理を止めてSlackに通知する。
"""
import sys
import os
import re
import csv
import logging
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_rules")

from config import SLACK_WEBHOOK_URL, SPREADSHEET_ID

FAILURES = []


def fail(test_name: str, detail: str):
    msg = f"❌ {test_name}: {detail}"
    logger.error(msg)
    FAILURES.append(msg)


def ok(test_name: str):
    logger.info(f"✅ {test_name}")


# ============================================================
# Test 1: auto_lister.py の price_usd 上限が2499以下
# ============================================================
def test_price_cap():
    with open(os.path.join(os.path.dirname(__file__), "auto_lister.py"), "r", encoding="utf-8") as f:
        code = f.read()

    # min(price_usd, XXXX) のパターンを検索
    matches = re.findall(r'price_usd\s*=\s*min\s*\(\s*price_usd\s*,\s*([\d.]+)\s*\)', code)
    if not matches:
        fail("price_cap", "price_usd の上限設定が見つからない")
        return

    for val in matches:
        cap = float(val)
        if cap > 2499.0:
            fail("price_cap", f"price_usd 上限が {cap} — 2499以下であるべき")
            return

    ok(f"price_cap: 上限 ${matches[0]}")


# ============================================================
# Test 2: sold_urls(items.csv)が存在し、出品シートと重複がないか
# ============================================================
def test_sold_urls_not_in_listings():
    base = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base, "items.csv")

    if not os.path.exists(csv_path):
        fail("sold_urls", "items.csv が存在しない")
        return

    # SOLD済みURL取得
    sold_urls = set()
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for key in ("mercari_url", "SOLD_URL"):
                url = row.get(key, "").strip()
                if url:
                    sold_urls.add(url)

    if not sold_urls:
        fail("sold_urls", "items.csv にURLが1件もない")
        return

    # 出品シートのURL取得
    from sheets_manager import _get_service
    from config import PRIORITY_SHEET_NAME, AUTO_SHEET_NAME, AUTO_SHEET_CARD, AUTO_SHEET_HOBBY, AUTO_SHEET_OTHER
    service = _get_service()
    listing_urls = set()
    for s_name in [PRIORITY_SHEET_NAME, AUTO_SHEET_NAME, AUTO_SHEET_CARD, AUTO_SHEET_HOBBY, AUTO_SHEET_OTHER]:
        try:
            res = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID, range=f"{s_name}!A2:E500"
            ).execute()
            for row in res.get("values", []):
                if row and row[0].strip():
                    status = row[4] if len(row) > 4 else ""
                    if "出品済み" not in status and "⛔" not in status and "SOLD" not in status:
                        listing_urls.add(row[0].strip())
        except:
            pass

    overlap = sold_urls & listing_urls
    if overlap:
        fail("sold_urls", f"SOLD済みURLが出品待ちに {len(overlap)}件: {list(overlap)[:3]}")
        return

    ok(f"sold_urls: items.csv {len(sold_urls)}件, 出品待ちとの重複なし")


# ============================================================
# Test 3: 出品待ちのメルカリURLが購入可能か（サンプルチェック）
# ============================================================
def test_listing_mercari_buyable():
    from sheets_manager import _get_service
    from mercari_checker import check_mercari_status
    from config import PRIORITY_SHEET_NAME, AUTO_SHEET_NAME, AUTO_SHEET_CARD

    service = _get_service()
    pending_urls = []
    for s_name in [PRIORITY_SHEET_NAME, AUTO_SHEET_CARD]:
        try:
            res = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID, range=f"{s_name}!A2:E100"
            ).execute()
            for row in res.get("values", []):
                if row and row[0].strip():
                    status = row[4] if len(row) > 4 else ""
                    if "出品済み" not in status and "⛔" not in status and "❌" not in status:
                        pending_urls.append(row[0].strip())
        except:
            pass

    if not pending_urls:
        ok("mercari_buyable: 出品待ち0件（チェック不要）")
        return

    # 最大5件サンプルチェック
    import random
    sample = random.sample(pending_urls, min(5, len(pending_urls)))
    unbuyable = []
    for url in sample:
        result = check_mercari_status(url, delay=1.0)
        if result.get("status") not in ("active", "error"):
            unbuyable.append(f"{url} → {result.get('status')}")

    if unbuyable:
        fail("mercari_buyable", f"購入不可の商品が出品待ちに: {unbuyable}")
        return

    ok(f"mercari_buyable: サンプル{len(sample)}件全て購入可能")


# ============================================================
# Test 4: inventory_manager.py がSOLD_URL参照を持つか
# ============================================================
def test_inventory_manager_sold_check():
    with open(os.path.join(os.path.dirname(__file__), "inventory_manager.py"), "r", encoding="utf-8") as f:
        code = f.read()

    checks = [
        ("load_sold_urls", "load_sold_urls関数が存在しない"),
        ("sold_urls", "sold_urls変数の参照がない"),
        ("SOLD_URL", "SOLD_URLフィールドの参照がない"),
    ]

    for keyword, err_msg in checks:
        if keyword not in code:
            fail("inventory_sold_check", err_msg)
            return

    # safe_restock関数にSOLD確認があるか
    if "safe_restock" not in code:
        fail("inventory_sold_check", "safe_restock関数がない")
        return

    ok("inventory_sold_check: load_sold_urls + safe_restock 存在確認OK")


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("🧪 出品前ルールチェック開始")
    logger.info("=" * 50)

    test_price_cap()
    test_sold_urls_not_in_listings()
    test_listing_mercari_buyable()
    test_inventory_manager_sold_check()

    logger.info("=" * 50)
    if FAILURES:
        logger.error(f"🚨 {len(FAILURES)}件のテスト失敗 — 出品を停止すべき")
        # Slack通知
        msg = f"🚨 test_rules.py 失敗 ({len(FAILURES)}件)\n" + "\n".join(FAILURES)
        try:
            requests.post(SLACK_WEBHOOK_URL, json={"text": msg}, timeout=10)
        except:
            pass
        sys.exit(1)
    else:
        logger.info("✅ 全テスト合格 — 出品OK")
        sys.exit(0)
