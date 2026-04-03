import os
import signal
import time
import subprocess
import logging
from datetime import datetime, timedelta
from sheets_manager import _get_service
from config import SPREADSHEET_ID, LISTING_SHEET_NAME, SLACK_WEBHOOK_URL
import requests

# ログ設定
logging.basicConfig(
    filename='/root/bot/logs/watchdog.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

LISTER_LOG = "/root/bot/logs/auto_lister.log"
LISTER_LOCK = "/tmp/auto_lister.lock"

def send_slack(message):
    if SLACK_WEBHOOK_URL:
        requests.post(SLACK_WEBHOOK_URL, json={"text": f"🛠️ [Watchdog] {message}"})

def clear_sheet_locks():
    """スプレッドシート上の『処理中』をクリアする"""
    try:
        service = _get_service()
        res = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, 
            range=f"{LISTING_SHEET_NAME}!A2:D200"
        ).execute()
        rows = res.get("values", [])
        
        updates = []
        for i, r in enumerate(rows):
            if len(r) > 3 and "処理中" in r[3]:
                updates.append({
                    "range": f"{LISTING_SHEET_NAME}!D{i+2}",
                    "values": [[""]]
                })
        
        if updates:
            batch_body = {"valueInputOption": "USER_ENTERED", "data": updates}
            service.spreadsheets().values().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=batch_body).execute()
            logger.info(f"Cleared {len(updates)} orphaned sheet locks.")
            return len(updates)
    except Exception as e:
        logger.error(f"Failed to clear sheet locks: {e}")
    return 0

def check_and_heal():
    """プロセスの停滞を検知し、強制再起動する"""
    now = datetime.now()
    
    # 1. ログの更新時間を確認
    if os.path.exists(LISTER_LOG):
        mtime = datetime.fromtimestamp(os.path.getmtime(LISTER_LOG))
        # 15分以上ログが動いていなければ異常とみなす
        if now - mtime > timedelta(minutes=15):
            logger.warning(f"Detection: auto_lister.py has stalled (No log update for 15+ mins).")
            
            # プロセスを強制終了
            subprocess.run(["pkill", "-f", "auto_lister.py"])
            if os.path.exists(LISTER_LOCK):
                os.remove(LISTER_LOCK)
            
            # シートのロックも掃除
            cleared = clear_sheet_locks()
            
            # 再起動
            subprocess.Popen(["python3", "/root/bot/auto_lister.py"], 
                             cwd="/root/bot", 
                             stdout=open(LISTER_LOG, "a"), 
                             stderr=subprocess.STDOUT)
            
            msg = f"自動出品の停滞を検知し、強制復旧しました（{cleared}件のロックを解除）。動作を再開しています。"
            send_slack(msg)
            logger.info("Self-healing completed.")

if __name__ == "__main__":
    check_and_heal()
