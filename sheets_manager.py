# ============================================================
#  sheets_manager.py  —  Google Sheets 読み書き
# ============================================================

import logging
import time
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from config import (
    SPREADSHEET_ID, SHEET_NAME, GOOGLE_CREDENTIALS_PATH,
    COL_MERCARI_URL, COL_MERCARI_ID, COL_EBAY_ITEM_ID,
    COL_STATUS, COL_LAST_CHECKED, COL_NOTES, DATA_START_ROW
)

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Retryable HTTP status codes (server-side / rate-limit errors)
_RETRYABLE_STATUS_CODES = {429, 500, 503}
_MAX_RETRIES = 3


def _retry_api_call(func, *args, **kwargs):
    """
    Google Sheets API の .execute() 呼び出しをリトライでラップするヘルパー。

    - リトライ対象: HttpError 429/500/503、接続エラー (OSError/ConnectionError)
    - リトライしない: HttpError 400/401/403 などクライアントエラー
    - バックオフ: 1s → 2s → 4s (指数バックオフ)
    - 最大リトライ回数: 3
    """
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except HttpError as e:
            status = e.resp.status
            if status not in _RETRYABLE_STATUS_CODES:
                # クライアントエラー(400/401/403など)はリトライしない
                raise
            last_exc = e
            if attempt < _MAX_RETRIES:
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(
                    f"Sheets API HttpError {status} (attempt {attempt + 1}/{_MAX_RETRIES}). "
                    f"{wait}s 後にリトライします..."
                )
                time.sleep(wait)
        except (OSError, ConnectionError) as e:
            last_exc = e
            if attempt < _MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning(
                    f"Sheets API 接続エラー (attempt {attempt + 1}/{_MAX_RETRIES}): {e}. "
                    f"{wait}s 後にリトライします..."
                )
                time.sleep(wait)
    raise last_exc


def _get_service():
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def read_active_items(sheet_name: str = SHEET_NAME) -> list[dict]:
    """
    スプレッドシートからステータスが "Active" のアイテムを取得する
    """
    service = _get_service()
    range_name = f"{sheet_name}!A{DATA_START_ROW}:H1500"
    req = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=range_name)
    result = _retry_api_call(req.execute)
    rows = result.get("values", [])
    items = []
    
    # 「出品」系シートの規約: A=URL, B=Profit(円), C=Price($), D=ItemID, E=Status
    is_listing_sheet = "出品" in sheet_name

    for i, row in enumerate(rows):
        while len(row) < 8: row.append("")
        m_url = row[0].strip() if is_listing_sheet else row[COL_MERCARI_URL].strip()
        # 出品シートならE列(4)、在庫管理表ならCOL_STATUS
        status = row[4].strip() if is_listing_sheet else row[COL_STATUS].strip()
        
        if not m_url or "出品済み" in status or "処理中" in status: continue

        item_data = {
            "row": DATA_START_ROW + i,
            "mercari_url": m_url,
            "status": status,
        }
        # 在庫管理表の場合は追加フィールドを含める
        if not is_listing_sheet:
            item_data["ebay_item_id"] = row[COL_EBAY_ITEM_ID].strip() if COL_EBAY_ITEM_ID >= 0 and COL_EBAY_ITEM_ID < len(row) else ""
            item_data["mercari_id"] = row[COL_MERCARI_ID].strip() if COL_MERCARI_ID >= 0 and COL_MERCARI_ID < len(row) else ""
        items.append(item_data)
    return items


def read_all_items(sheet_name: str = SHEET_NAME) -> list[dict]:
    """全件読み込み（ステータス問わず）"""
    service = _get_service()
    range_name = f"{sheet_name}!A{DATA_START_ROW}:H5000"
    req = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=range_name
    )
    result = _retry_api_call(req.execute)
    rows = result.get("values", [])
    items = []
    for i, row in enumerate(rows):
        while len(row) < 8:
            row.append("")
        if not row[COL_MERCARI_URL].strip():
            continue
        ebay_item_id = row[COL_EBAY_ITEM_ID].strip() if COL_EBAY_ITEM_ID >= 0 and COL_EBAY_ITEM_ID < len(row) else ""
        last_checked = row[COL_LAST_CHECKED].strip() if COL_LAST_CHECKED >= 0 and COL_LAST_CHECKED < len(row) else ""
        items.append({
            "row": DATA_START_ROW + i,
            "mercari_url": row[COL_MERCARI_URL].strip(),
            "mercari_id": row[COL_MERCARI_ID].strip() if COL_MERCARI_ID < len(row) else "",
            "ebay_item_id": ebay_item_id,
            "status": row[COL_STATUS].strip() if COL_STATUS < len(row) else "",
            "last_checked": last_checked,
            "notes": row[COL_NOTES].strip() if COL_NOTES < len(row) else "",
        })
    return items


def update_item_status(row: int, status: str, sheet_name: str = SHEET_NAME) -> None:
    """
    特定行のステータスを更新する
    """
    service = _get_service()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    values = [[status]]
    # 規約: A=URL, B=Profit, C=Price, D=ItemID, E=Status
    is_listing_sheet = "出品" in sheet_name
    col_letter = "E" if is_listing_sheet else "D" 
    range_name = f"{sheet_name}!{col_letter}{row}"

    req = service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=range_name,
        valueInputOption="RAW",
        body={"values": values}
    )
    _retry_api_call(req.execute)

    logger.info(f"行 {row} → ステータス: {status}, 更新日時: {now}")


def batch_update_statuses(updates: list[dict]) -> None:
    """
    複数行を一括更新する（API呼び出しを最小化）

    Args:
        updates: [{"row": int, "status": str, "notes": str}, ...]
    """
    if not updates:
        return

    service = _get_service()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    data = []
    for u in updates:
        row = u["row"]
        status = u["status"]
        s_name = u.get("sheet_name", SHEET_NAME)
        data.append({
            "range": f"{s_name}!F{row}",
            "values": [[status]]
        })

    body = {"valueInputOption": "RAW", "data": data}
    req = service.spreadsheets().values().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body=body
    )
    _retry_api_call(req.execute)

    logger.info(f"{len(updates)} 件のステータスを一括更新しました")


def get_summary() -> dict:
    """シート全体のサマリーを返す"""
    items = read_all_items()
    total = len(items)
    active = sum(1 for i in items if i["status"].lower() not in ("outofstock", "ended"))
    oos    = sum(1 for i in items if i["status"].lower() == "outofstock")
    ended  = sum(1 for i in items if i["status"].lower() == "ended")
    return {
        "total": total,
        "active": active,
        "out_of_stock": oos,
        "ended": ended
    }


def get_sheet_id_by_name(service, sheet_name: str) -> int:
    """シート名から sheetId を動的に取得する"""
    req = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID)
    sheet_metadata = _retry_api_call(req.execute)
    sheets = sheet_metadata.get('sheets', '')
    for sheet in sheets:
        if sheet.get("properties", {}).get("title", "") == sheet_name:
            return sheet.get("properties", {}).get("sheetId", 0)
    return 0


def delete_rows(sheet_name: str, row_indices: list[int]) -> None:
    """
    指定された行番号(1-indexed)のリストをシートから完全に削除する。
    行のインデックスがズレるのを防ぐため、内部で大きい行番号から順に削除処理を行う。
    """
    if not row_indices:
        return
        
    service = _get_service()
    sheet_id = get_sheet_id_by_name(service, sheet_name)
    
    # 重複排除 & 降順ソート
    sorted_rows = sorted(list(set(row_indices)), reverse=True)
    requests = []
    
    for row in sorted_rows:
        requests.append({
            "deleteDimension": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": row - 1,  # Google Sheets API は0-indexed
                    "endIndex": row
                }
            }
        })

    if requests:
        body = {"requests": requests}
        req = service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=body
        )
        _retry_api_call(req.execute)
        logger.info(f"{sheet_name} から対象の {len(requests)} 行を削除しました。")


def append_item_to_inventory(mercari_url: str, ebay_item_id: str) -> None:
    """
    新しく出品した商品を「在庫管理表」(Master Sheet)の最下部に追加する。
    """
    service = _get_service()
    # 在庫管理表のフォーマットに合わせて配置
    row_data = [""] * 8
    row_data[COL_EBAY_ITEM_ID] = str(ebay_item_id)
    row_data[COL_MERCARI_URL] = mercari_url
    row_data[COL_STATUS] = "Active"
    
    body = {"values": [row_data]}
    
    req = service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1:H1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body
    )
    _retry_api_call(req.execute)
    logger.info(f"在庫管理表に新しい商品を追加しました: {ebay_item_id} / {mercari_url}")


def create_sheet_if_not_exists(sheet_name: str) -> None:
    """シートが存在しない場合に新規作成する"""
    service = _get_service()
    try:
        req = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID, ranges=[f"{sheet_name}!A1"])
        _retry_api_call(req.execute)
    except Exception:
        logger.info(f"シート '{sheet_name}' を作成中...")
        body = {"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}
        req_create = service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=body)
        _retry_api_call(req_create.execute)
        # ヘッダー (A=URL, B=Price, C=ItemID, D=Status)
        headers = [["メルカリURL", "出品価格($)", "eBayItemID", "Status", "Notes"]]
        req_header = service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID, range=f"{sheet_name}!A1",
            valueInputOption="RAW", body={"values": headers}
        )
        _retry_api_call(req_header.execute)

def clear_sheet_v2(sheet_name: str) -> None:
    """00:00のリセット。データ行を全削除する"""
    service = _get_service()
    sheet_id = get_sheet_id_by_name(service, sheet_name)
    # A2以降をクリア
    body = {
        "requests": [{
            "updateCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1, # 2行目以降
                },
                "fields": "userEnteredValue"
            }
        }]
    }
    req = service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=body)
    _retry_api_call(req.execute)
    logger.info(f"シート {sheet_name} のデータ行をクリアしました（00:00リセット）")
