#!/usr/bin/env python3
"""
progress_reporter.py — 1時間ごとの進捗報告

出品数・残り件数・エラー件数をSlackに報告する。
cronで毎時実行: 0 * * * * cd /root/bot && python3 progress_reporter.py
"""

import sys
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

from config import (
    EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID,
    EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV,
    SLACK_WEBHOOK_URL, SLACK_WEBHOOK_URL_ORDERS
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

EBAY_ENDPOINT = {
    "production": "https://api.ebay.com/ws/api.dll",
    "sandbox":    "https://api.sandbox.ebay.com/ws/api.dll"
}.get(EBAY_ENV, "https://api.ebay.com/ws/api.dll")

TARGET_LISTINGS = 1100


def get_active_count() -> int:
    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "GetMyeBaySelling",
        "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml",
    }
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <ActiveList>
    <Include>true</Include>
    <Pagination><EntriesPerPage>1</EntriesPerPage><PageNumber>1</PageNumber></Pagination>
  </ActiveList>
</GetMyeBaySellingRequest>"""
    try:
        resp = requests.post(EBAY_ENDPOINT, headers=headers, data=xml.encode("utf-8"), timeout=30)
        root = ET.fromstring(resp.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
        total = root.find(".//ns:ActiveList/ns:PaginationResult/ns:TotalNumberOfEntries", ns)
        return int(total.text) if total is not None else -1
    except Exception as e:
        logger.error(f"Active件数取得失敗: {e}")
        return -1


def count_supervisor_blocks() -> int:
    """今日のsupervisorブロック件数"""
    import os
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "supervisor_audit.log")
    if not os.path.exists(log_path):
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    count = 0
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith(today) and "BLOCKED" in line:
                count += 1
    return count


def report():
    now = datetime.now()
    active = get_active_count()
    remaining = max(0, TARGET_LISTINGS - active)
    blocks = count_supervisor_blocks()

    msg = (
        f"[進捗報告 {now.strftime('%H:%M')}]\n"
        f"Active出品数: {active}件\n"
        f"目標まで残り: {remaining}件\n"
        f"監視ブロック: {blocks}件（本日）"
    )

    if active >= TARGET_LISTINGS:
        msg += "\n目標達成"

    logger.info(msg)

    webhook = SLACK_WEBHOOK_URL_ORDERS or SLACK_WEBHOOK_URL
    if webhook:
        try:
            requests.post(webhook, json={"text": msg}, timeout=10)
        except:
            pass

    return {"active": active, "remaining": remaining, "blocks": blocks}


if __name__ == "__main__":
    result = report()
    print(f"Active: {result['active']} | 残り: {result['remaining']} | ブロック: {result['blocks']}")
