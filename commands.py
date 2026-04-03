#!/usr/bin/env python3
"""
commands.py — 運用コマンド集
morning_briefing / sourcing_report / price_check / queue_status / fix_errors
"""

import sys
import json
import logging
import time
from datetime import datetime, timedelta
from collections import Counter
from config import (
    SPREADSHEET_ID, SHEET_NAME, EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID,
    EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV, EXCHANGE_RATE, SHIPPING_COST_JPY,
    AUTO_SHEET_CARD, AUTO_SHEET_HOBBY, AUTO_SHEET_OTHER, AUTO_SHEETS,
    PRIORITY_SHEET_NAME, SLACK_WEBHOOK_URL
)
from sheets_manager import _get_service, read_all_items, read_active_items
import requests
import xml.etree.ElementTree as ET

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ENDPOINT = {
    "production": "https://api.ebay.com/ws/api.dll",
    "sandbox": "https://api.sandbox.ebay.com/ws/api.dll"
}.get(EBAY_ENV, "https://api.ebay.com/ws/api.dll")

def _ebay_headers(call_name):
    return {
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": call_name,
        "X-EBAY-API-SITEID": EBAY_SITE_ID,
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml",
    }


# ============================================================
#  /morning-briefing
# ============================================================
def morning_briefing():
    """昨夜の売上・新着注文・キュー在庫数・要対応メッセージ"""
    print("=" * 50)
    print("  MORNING BRIEFING")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    # 1. 最近の注文
    print("\n■ 新着注文（過去24時間）")
    try:
        since = (datetime.utcnow() - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetOrdersRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <CreateTimeFrom>{since}</CreateTimeFrom>
  <CreateTimeTo>{datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")}</CreateTimeTo>
  <OrderRole>Seller</OrderRole>
  <OrderStatus>All</OrderStatus>
</GetOrdersRequest>"""
        resp = requests.post(ENDPOINT, headers=_ebay_headers("GetOrders"), data=xml.encode("utf-8"), timeout=30)
        root = ET.fromstring(resp.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
        orders = root.findall(".//ns:Order", ns)
        total_sales = 0
        for o in orders:
            total_el = o.find("ns:Total", ns)
            title_el = o.find(".//ns:Transaction/ns:Item/ns:Title", ns)
            status_el = o.find("ns:OrderStatus", ns)
            amt = float(total_el.text) if total_el is not None else 0
            total_sales += amt
            t = title_el.text[:50] if title_el is not None else "?"
            s = status_el.text if status_el is not None else "?"
            print(f"  ${amt:.2f} | {s} | {t}")
        if not orders:
            print("  なし")
        else:
            print(f"  → 合計: ${total_sales:.2f}（{len(orders)}件）")
    except Exception as e:
        print(f"  取得失敗: {e}")

    # 2. アクティブ出品数
    print("\n■ アクティブ出品数")
    try:
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <ActiveList><Pagination><EntriesPerPage>1</EntriesPerPage><PageNumber>1</PageNumber></Pagination></ActiveList>
</GetMyeBaySellingRequest>"""
        resp = requests.post(ENDPOINT, headers=_ebay_headers("GetMyeBaySelling"), data=xml.encode("utf-8"), timeout=30)
        root = ET.fromstring(resp.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
        total = root.find(".//ns:ActiveList/ns:PaginationResult/ns:TotalNumberOfEntries", ns)
        print(f"  eBayアクティブ: {total.text if total is not None else '?'}件")
    except Exception as e:
        print(f"  取得失敗: {e}")

    # 3. キュー状況
    print("\n■ 出品キュー")
    queue_status()

    # 4. 要対応メッセージ
    print("\n■ 未読メッセージ")
    try:
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyMessagesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <FolderID>0</FolderID>
  <StartTime>{(datetime.utcnow() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S.000Z")}</StartTime>
  <EndTime>{datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")}</EndTime>
  <DetailLevel>ReturnHeaders</DetailLevel>
</GetMyMessagesRequest>"""
        resp = requests.post(ENDPOINT, headers=_ebay_headers("GetMyMessages"), data=xml.encode("utf-8"), timeout=30)
        root = ET.fromstring(resp.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
        msgs = root.findall(".//ns:Message", ns)
        unread = [m for m in msgs if m.find("ns:Read", ns) is not None and m.find("ns:Read", ns).text == "false"]
        if unread:
            for m in unread[:5]:
                subj = m.find("ns:Subject", ns)
                sender = m.find("ns:Sender", ns)
                print(f"  [{sender.text if sender is not None else '?'}] {subj.text if subj is not None else '?'}")
            if len(unread) > 5:
                print(f"  ... 他{len(unread)-5}件")
        else:
            print("  なし")
    except Exception as e:
        print(f"  取得失敗: {e}")

    # 5. 在庫監視の最終実行
    print("\n■ 在庫監視")
    try:
        import os
        log_path = os.path.join(os.path.dirname(__file__) or ".", "cron.log")
        if os.path.exists(log_path):
            with open(log_path) as f:
                lines = f.readlines()
            if lines:
                last = lines[-1].strip()
                print(f"  最終ログ: {last[:80]}")
            today = datetime.now().strftime("%Y-%m-%d")
            today_lines = [l for l in lines if today in l]
            sold = sum(1 for l in today_lines if "売り切れ" in l or "❌" in l)
            print(f"  今日の売り切れ検知: {sold}件")
    except:
        print("  ログ読み取り失敗")

    print("\n" + "=" * 50)


# ============================================================
#  /sourcing-report
# ============================================================
def sourcing_report():
    """各部門のリサーチ結果サマリー"""
    print("=" * 50)
    print("  SOURCING REPORT")
    print("=" * 50)

    import os
    sourcing_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sourcing")
    depts = []
    if os.path.isdir(sourcing_dir):
        for name in sorted(os.listdir(sourcing_dir)):
            kw_file = os.path.join(sourcing_dir, name, "keywords.json")
            if os.path.exists(kw_file):
                with open(kw_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                depts.append(data)

    if not depts:
        print("  部署設定なし")
        return

    # 各シートの内容を取得
    service = _get_service()
    for sheet_name in AUTO_SHEETS:
        try:
            res = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID, range=f"{sheet_name}!A2:F500"
            ).execute()
            rows = res.get("values", [])
            total = len(rows)
            pending = sum(1 for r in rows if len(r) > 4 and "完了" in r[4] and (len(r) < 4 or not r[3]))
            listed = sum(1 for r in rows if len(r) > 4 and "出品済み" in r[4])
            failed = sum(1 for r in rows if len(r) > 4 and "❌" in r[4])
            print(f"\n  [{sheet_name}] 合計{total}件: 待機{pending} / 出品済{listed} / 失敗{failed}")
        except:
            print(f"\n  [{sheet_name}] 読み取り失敗")

    print(f"\n■ 稼働中の部署")
    for d in depts:
        name = d.get("department", "?")
        kws = len(d.get("mercari_keywords", []))
        print(f"  {name}: {kws}キーワード")

    print()


# ============================================================
#  /price-check
# ============================================================
def price_check(query: str):
    """eBay Sold価格を取得して利益計算"""
    print(f"■ Price Check: {query}")
    try:
        from ebay_price_checker import get_market_price, get_sold_velocity
        market = get_market_price(query)
        velocity = get_sold_velocity(query, days=7)
        print(f"  eBay相場: ${market:.2f}" if market else "  eBay相場: データなし")
        print(f"  7日間Sold: {velocity}件")

        if market and market > 0:
            # 仕入れ価格別の利益テーブル
            print(f"\n  仕入値  →  利益      ROI")
            print(f"  {'─'*35}")
            for cost_jpy in [3000, 5000, 8000, 10000, 15000, 20000]:
                revenue_jpy = market * EXCHANGE_RATE
                fees = revenue_jpy * 0.196
                profit = revenue_jpy - fees - cost_jpy - SHIPPING_COST_JPY + (cost_jpy * 0.1)
                roi = profit / cost_jpy * 100 if cost_jpy > 0 else 0
                mark = "✅" if profit >= 3000 and roi >= 25 else "  "
                print(f"  ¥{cost_jpy:>6,}  →  ¥{int(profit):>6,}  {roi:>5.0f}%  {mark}")
    except Exception as e:
        print(f"  エラー: {e}")
    print()


# ============================================================
#  /queue-status
# ============================================================
def queue_status():
    """3つの自動出品シートの待機中・出品済み・失敗件数"""
    service = _get_service()
    for sheet_name in [PRIORITY_SHEET_NAME] + AUTO_SHEETS:
        try:
            res = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID, range=f"{sheet_name}!A2:F500"
            ).execute()
            rows = res.get("values", [])
            pending = 0
            listed = 0
            failed = 0
            for r in rows:
                status = r[4] if len(r) > 4 else ""
                has_id = len(r) > 3 and r[3].strip().isdigit()
                if "出品済み" in status or has_id:
                    listed += 1
                elif "❌" in status:
                    failed += 1
                elif r[0].strip():
                    pending += 1
            print(f"  {sheet_name}: 待機{pending} / 出品済{listed} / 失敗{failed}")
        except:
            print(f"  {sheet_name}: 読み取り失敗")


# ============================================================
#  /fix-errors
# ============================================================
def fix_errors():
    """出品失敗行を一括確認して修正方針を提示"""
    print("=" * 50)
    print("  FIX ERRORS — 出品失敗の診断")
    print("=" * 50)

    service = _get_service()
    error_summary = Counter()
    error_details = []

    for sheet_name in [PRIORITY_SHEET_NAME] + AUTO_SHEETS:
        try:
            res = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID, range=f"{sheet_name}!A2:F500"
            ).execute()
            rows = res.get("values", [])
            for i, r in enumerate(rows):
                status = r[4] if len(r) > 4 else ""
                if "❌" in status:
                    url = r[0] if r else ""
                    # エラー種別を分類
                    if "スクレイプ失敗" in status:
                        error_summary["スクレイプ失敗"] += 1
                        error_details.append((sheet_name, i+2, "スクレイプ失敗", url[:50]))
                    elif "improper words" in status.lower() or "title" in status.lower():
                        error_summary["NGワード"] += 1
                        error_details.append((sheet_name, i+2, "NGワード", url[:50]))
                    elif "item specifics" in status.lower() or "Year" in status:
                        error_summary["Item Specifics"] += 1
                        error_details.append((sheet_name, i+2, "Item Specifics", url[:50]))
                    elif "AI" in status:
                        error_summary["AI分析失敗"] += 1
                        error_details.append((sheet_name, i+2, "AI分析失敗", url[:50]))
                    elif "画像" in status:
                        error_summary["画像転送失敗"] += 1
                        error_details.append((sheet_name, i+2, "画像転送失敗", url[:50]))
                    elif "利益不足" in status or "価格" in status:
                        error_summary["採算NG"] += 1
                        error_details.append((sheet_name, i+2, "採算NG", url[:50]))
                    else:
                        error_summary["その他"] += 1
                        error_details.append((sheet_name, i+2, status[:30], url[:50]))
        except:
            pass

    if not error_summary:
        print("\n  ✅ エラーなし！全件正常です。")
        return

    print(f"\n■ エラー集計（合計{sum(error_summary.values())}件）")
    for err, cnt in error_summary.most_common():
        print(f"  x{cnt}: {err}")

    print(f"\n■ 修正方針")
    if "スクレイプ失敗" in error_summary:
        print(f"  スクレイプ失敗({error_summary['スクレイプ失敗']}件): メルカリ側が売り切れ or URL無効の可能性。該当行を削除推奨。")
    if "NGワード" in error_summary:
        print(f"  NGワード({error_summary['NGワード']}件): タイトルにeBay禁止ワードあり。AI再生成で解決可能。")
    if "Item Specifics" in error_summary:
        print(f"  Item Specifics({error_summary['Item Specifics']}件): Year等の値不正。修正済み（自動バリデーション追加）。再実行で解決。")
    if "AI分析失敗" in error_summary:
        print(f"  AI分析失敗({error_summary['AI分析失敗']}件): Gemini APIのレート制限 or タイムアウト。時間を空けて再実行。")
    if "画像転送失敗" in error_summary:
        print(f"  画像転送失敗({error_summary['画像転送失敗']}件): eBay EPS一時障害の可能性。再実行で解決。")
    if "採算NG" in error_summary:
        print(f"  採算NG({error_summary['採算NG']}件): 利益基準未達。対応不要（正常なフィルタ）。")

    print(f"\n■ 詳細（先頭10件）")
    for sheet, row, err_type, url in error_details[:10]:
        print(f"  {sheet} 行{row}: [{err_type}] {url}")
    if len(error_details) > 10:
        print(f"  ... 他{len(error_details)-10}件")

    print()


# ============================================================
#  CLI
# ============================================================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方:")
        print("  python3 commands.py morning-briefing")
        print("  python3 commands.py sourcing-report")
        print("  python3 commands.py price-check <検索クエリ>")
        print("  python3 commands.py queue-status")
        print("  python3 commands.py fix-errors")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "morning-briefing":
        morning_briefing()
    elif cmd == "sourcing-report":
        sourcing_report()
    elif cmd == "price-check":
        if len(sys.argv) < 3:
            print("検索クエリを指定してください: python3 commands.py price-check 'One Piece PSA 10'")
            sys.exit(1)
        price_check(" ".join(sys.argv[2:]))
    elif cmd == "queue-status":
        queue_status()
    elif cmd == "fix-errors":
        fix_errors()
    else:
        print(f"不明なコマンド: {cmd}")
