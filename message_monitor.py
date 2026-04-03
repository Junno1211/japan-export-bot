#!/usr/bin/env python3
"""
message_monitor.py — eBayメッセージ・問い合わせ監視
バイヤーからのメッセージを日本語翻訳＋仕入先URL付きでSlack通知
"""

import os
import sys
import json
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import (
    EBAY_AUTH_TOKEN, EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID,
    EBAY_SITE_ID, EBAY_ENV, GEMINI_API_KEY, SPREADSHEET_ID
)
try:
    from config import SLACK_WEBHOOK_URL_MESSAGES as SLACK_WEBHOOK_URL
except ImportError:
    from config import SLACK_WEBHOOK_URL
import sheets_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PROCESSED_MESSAGES_FILE = os.path.join(os.path.dirname(__file__), "processed_messages.json")
ENDPOINT = "https://api.ebay.com/ws/api.dll" if EBAY_ENV == "production" else "https://api.sandbox.ebay.com/ws/api.dll"
HEADERS = {
    "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
    "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
    "X-EBAY-API-APP-NAME": EBAY_APP_ID,
    "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
    "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
    "Content-Type": "text/xml",
}
NS = {"ns": "urn:ebay:apis:eBLBaseComponents"}


def send_slack(text: str):
    if not SLACK_WEBHOOK_URL:
        return
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
    except Exception as e:
        logger.error(f"Slack送信失敗: {e}")


def load_processed() -> set:
    if os.path.exists(PROCESSED_MESSAGES_FILE):
        with open(PROCESSED_MESSAGES_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_processed(ids: set):
    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(PROCESSED_MESSAGES_FILE), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(list(ids), f)
        os.replace(tmp_path, PROCESSED_MESSAGES_FILE)
    except:
        os.unlink(tmp_path)
        raise


def summarize_message(text: str) -> str:
    """Gemini APIでメッセージを要約。最新メッセージのみ抽出→日本語で3行以内に"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = (
        "あなたはeBayセラーの秘書です。以下のeBayメッセージから：\n"
        "1. 最新のバイヤーのメッセージだけを抽出（過去のやり取り・引用・eBayフッター・免責文は全て無視）\n"
        "2. 日本語で1行に要約\n"
        "3. セラーが今すべきアクションを1行で書く\n\n"
        "フォーマット（これだけ返して）:\n"
        "要約: （バイヤーが言ってること）\n"
        "対応: （セラーがすべきこと）\n\n"
        f"メッセージ:\n{text}"
    )
    try:
        resp = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=20)
        if resp.status_code == 200:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except:
        pass
    return text


def find_source_url(item_id: str) -> str:
    """在庫管理表からeBay ItemIDに対応する仕入先URLと商品名を取得"""
    try:
        service = sheets_manager._get_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='在庫管理表!A2:D500'
        ).execute()
        rows = result.get('values', [])
        for row in rows:
            if len(row) > 3 and row[0].strip() == str(item_id):
                name = row[1].strip() if len(row) > 1 else ""
                source = row[2].strip() if len(row) > 2 else ""
                url = row[3].strip()
                return url, name, source
    except Exception as e:
        logger.error(f"Sheet search error: {e}")
    return "特定できず", "", ""


def get_message_ids():
    """直近2日間のメッセージID一覧を取得"""
    now = datetime.now(timezone.utc)
    from_time = (now - timedelta(days=2)).replace(microsecond=0).isoformat()
    to_time = now.replace(microsecond=0).isoformat()

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyMessagesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <StartTime>{from_time}</StartTime>
  <EndTime>{to_time}</EndTime>
  <FolderID>0</FolderID>
  <DetailLevel>ReturnHeaders</DetailLevel>
</GetMyMessagesRequest>"""

    headers = {**HEADERS, "X-EBAY-API-CALL-NAME": "GetMyMessages"}
    try:
        resp = requests.post(ENDPOINT, headers=headers, data=xml.encode("utf-8"), timeout=30)
        root = ET.fromstring(resp.text)
        ack = root.find("ns:Ack", NS)
        if ack is None or ack.text not in ("Success", "Warning"):
            logger.error(f"GetMyMessages Error: {resp.text[:500]}")
            return []

        messages = []
        for msg in root.findall(".//ns:Message", NS):
            msg_id = msg.find("ns:MessageID", NS)
            if msg_id is not None:
                messages.append(msg_id.text)
        return messages
    except Exception as e:
        logger.error(f"GetMyMessages Exception: {e}")
        return []


def get_message_detail(message_id: str) -> dict:
    """メッセージの詳細を取得"""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyMessagesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <MessageIDs>
    <MessageID>{message_id}</MessageID>
  </MessageIDs>
  <DetailLevel>ReturnMessages</DetailLevel>
</GetMyMessagesRequest>"""

    headers = {**HEADERS, "X-EBAY-API-CALL-NAME": "GetMyMessages"}
    try:
        resp = requests.post(ENDPOINT, headers=headers, data=xml.encode("utf-8"), timeout=30)
        root = ET.fromstring(resp.text)

        msg = root.find(".//ns:Message", NS)
        if msg is None:
            return {}

        sender = msg.find("ns:Sender", NS)
        subject = msg.find("ns:Subject", NS)
        text_el = msg.find("ns:Text", NS)
        item_id_el = msg.find("ns:ItemID", NS)
        msg_type = msg.find("ns:MessageType", NS)

        return {
            "message_id": message_id,
            "sender": sender.text if sender is not None else "不明",
            "subject": subject.text if subject is not None else "",
            "body": text_el.text if text_el is not None else "",
            "item_id": item_id_el.text if item_id_el is not None else "",
            "type": msg_type.text if msg_type is not None else "",
        }
    except Exception as e:
        logger.error(f"GetMessage Detail Error: {e}")
        return {}


def main():
    logger.info("📨 eBayメッセージ監視開始")
    processed = load_processed()
    message_ids = get_message_ids()

    if not message_ids:
        logger.info("新しいメッセージはありません")
        return

    new_count = 0
    for mid in message_ids:
        if mid in processed:
            continue

        detail = get_message_detail(mid)
        if not detail:
            continue

        # eBayシステムメッセージはスキップ
        if detail.get("type") == "System":
            processed.add(mid)
            continue

        # 仕入先URL取得
        item_id = detail.get("item_id", "")
        source_url, product_name, source_name = "", "", ""
        if item_id:
            source_url, product_name, source_name = find_source_url(item_id)

        # AI要約（最新メッセージのみ→日本語→アクション付き）
        body_raw = detail.get("body", "") or detail.get("subject", "")
        summary = summarize_message(body_raw)

        # Slack通知（3行以内）
        msg = f"*📨 {detail.get('sender', '不明')}*\n{summary}"
        if item_id and source_url != "特定できず":
            msg += f"\n仕入先: {source_url}"
        elif item_id:
            msg += f"\neBay: https://www.ebay.com/itm/{item_id}"

        send_slack(msg)
        logger.info(f"✅ メッセージ通知: {detail.get('sender')} - {detail.get('subject', '')[:30]}")
        processed.add(mid)
        new_count += 1

    save_processed(processed)
    logger.info(f"📨 完了: 新規{new_count}件通知")


if __name__ == "__main__":
    main()
