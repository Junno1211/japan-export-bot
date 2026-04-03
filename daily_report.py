import os
import sys
import csv
import logging
import requests
from datetime import datetime
from xml.etree import ElementTree as ET

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import (
    SLACK_WEBHOOK_URL, EBAY_AUTH_TOKEN, EBAY_SITE_ID,
    EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID, EBAY_ENV
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ITEMS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "items.csv")


def send_slack(text: str):
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL is not set.")
        return
    requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)


def get_today_listed() -> int:
    """items.csvから当日分の出品数を集計"""
    today_str = datetime.now().strftime("%Y-%m-%d")
    count = 0
    if not os.path.exists(ITEMS_CSV):
        return 0
    try:
        with open(ITEMS_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                for key in ("date", "timestamp", "created_at"):
                    val = row.get(key, "")
                    if today_str in val:
                        count += 1
                        break
    except Exception as e:
        logger.error(f"items.csv読み込みエラー: {e}")
    return count


def get_sold_out_count() -> int:
    """inventory_manager.pyの当日ログから売り切れ検知数を集計"""
    today_str = datetime.now().strftime("%Y%m%d")
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", f"inventory_{today_str}.log")
    count = 0
    if not os.path.exists(log_path):
        return 0
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                if "⛔ 売り切れ" in line or "⛔ 購入手続きボタンなし" in line or "⛔ オークション変更検出" in line:
                    count += 1
    except Exception as e:
        logger.error(f"ログ読み込みエラー: {e}")
    return count


def get_active_count() -> int:
    """eBay GetMyeBaySelling APIでアクティブ出品数を取得"""
    endpoint = "https://api.ebay.com/ws/api.dll" if EBAY_ENV.upper() == "PRODUCTION" else "https://api.sandbox.ebay.com/ws/api.dll"
    headers = {
        "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
        "X-EBAY-API-COMPATIBILITY-LEVEL": "1131",
        "X-EBAY-API-CALL-NAME": "GetMyeBaySelling",
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml",
    }
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <ActiveList>
    <Pagination>
      <EntriesPerPage>1</EntriesPerPage>
      <PageNumber>1</PageNumber>
    </Pagination>
  </ActiveList>
</GetMyeBaySellingRequest>"""
    try:
        resp = requests.post(endpoint, headers=headers, data=xml.encode("utf-8"), timeout=30)
        root = ET.fromstring(resp.text)
        ns = {"e": "urn:ebay:apis:eBLBaseComponents"}
        total = root.findtext(".//e:ActiveList/e:PaginationResult/e:TotalNumberOfEntries", namespaces=ns)
        return int(total) if total else 0
    except Exception as e:
        logger.error(f"eBay API エラー: {e}")
        return 0


def main():
    logger.info("毎朝レポート生成開始...")
    today_listed = get_today_listed()
    sold_out_count = get_sold_out_count()
    active_count = get_active_count()

    msg = (
        f"おはようございます！🌅 JAPAN EXPORT 本日のレポート\n\n"
        f"📦 本日の出品数: {today_listed}件\n"
        f"📉 売り切れ検知: {sold_out_count}件 → eBay在庫0済み\n"
        f"🏪 現在のアクティブ出品数: {active_count}件"
    )
    send_slack(msg)
    logger.info("レポート送信完了")


if __name__ == "__main__":
    main()
