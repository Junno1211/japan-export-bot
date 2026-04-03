import time
import logging
from config import SPREADSHEET_ID, AUTO_SHEET_NAME
from sheets_manager import _get_service

logger = logging.getLogger(__name__)

def update_heartbeat(status_text: str):
    """
    スプレッドシートの「自動出品」タブの特定のセル（例：H1）に現在時刻とステータスを書き込む
    """
    try:
        service = _get_service()
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        full_status = f"🕒 Last Heartbeat: {now_str} | Status: {status_text}"
        
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{AUTO_SHEET_NAME}!H1",
            valueInputOption="USER_ENTERED",
            body={"values": [[full_status]]}
        ).execute()
        # logging.info(f"❤️ Heartbeat: {status_text}")
    except Exception as e:
        logger.warning(f"Heartbeat update failed: {e}")

if __name__ == "__main__":
    update_heartbeat("System Standby")
