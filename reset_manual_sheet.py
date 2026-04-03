import sys
import logging
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

API_KEY_FILE = os.getenv("GOOGLE_CREDENTIALS_PATH", "google_credentials.json")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1dlRcKP4tKubmubrO-_kYo2y9cfN867ZUbHUMYjp4280")
MANUAL_SHEET_NAME = "手動出品"

def reset_manual_sheet():
    logger.info("手動出品シートのステータスをリセット中...")
    try:
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_service_account_file(API_KEY_FILE, scopes=scopes)
        service = build('sheets', 'v4', credentials=creds)

        # Clear C2:D100
        service.spreadsheets().values().clear(
            spreadsheetId=SPREADSHEET_ID,
            range=f"'{MANUAL_SHEET_NAME}'!C2:D100"
        ).execute()

        logger.info("✅ ステータスとログをリセットしました！これにより再同期が開始されます。")
    except Exception as e:
        logger.error(f"エラー: {e}")

if __name__ == "__main__":
    reset_manual_sheet()
