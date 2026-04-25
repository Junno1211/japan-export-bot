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
    COL_STATUS, COL_LAST_CHECKED, COL_NOTES, DATA_START_ROW,
    PRIORITY_SHEET_NAME, AUTO_SHEET_NAME, AUTO_SHEETS,
)

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _norm_sheet_title(s: str) -> str:
    """タブ名の前後空白を除去（API 照合・出品キュー判定の取り違え防止）。"""
    return (s or "").strip()


def _a1_range(sheet_name: str, cell_a1: str) -> str:
    """
    Google Sheets API 用 A1。日本語タブ名などは ' で囲む。
    cell_a1 例: A2:H500, E33, C33:E33
    """
    name = _norm_sheet_title(sheet_name) or "Sheet1"
    return "'" + name.replace("'", "''") + "'!" + cell_a1

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


def _is_listing_queue_sheet(sheet_name: str) -> bool:
    """出品待ちキュー（A=URL,B=利益,…,E=Status）。タブ名に「出品」が無い「手動」も含む。"""
    s = _norm_sheet_title(sheet_name)
    if s == _norm_sheet_title(PRIORITY_SHEET_NAME) or s == _norm_sheet_title(AUTO_SHEET_NAME):
        return True
    for _auto in AUTO_SHEETS:
        if s == _norm_sheet_title(_auto):
            return True
    return "出品" in s


def read_active_items(sheet_name: str = SHEET_NAME) -> list[dict]:
    """
    スプレッドシートからステータスが "Active" のアイテムを取得する
    """
    service = _get_service()
    range_name = _a1_range(sheet_name, f"A{DATA_START_ROW}:H1500")
    req = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=range_name)
    result = _retry_api_call(req.execute)
    rows = result.get("values", [])
    items = []
    
    # 出品待ちキュー系の規約: A=URL, B=Profit(円), C=Price($), D=ItemID, E=Status
    is_listing_sheet = _is_listing_queue_sheet(sheet_name)

    for i, row in enumerate(rows):
        while len(row) < 8: row.append("")
        m_url = row[0].strip() if is_listing_sheet else row[COL_MERCARI_URL].strip()
        # 出品シートならE列(4)、在庫管理表ならCOL_STATUS
        status = row[4].strip() if is_listing_sheet else row[COL_STATUS].strip()
        
        # 「出品済み」は再処理しない。「処理中」はクラッシュ復旧のため次回も拾う。
        if not m_url or "出品済み" in status:
            continue

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
    range_name = _a1_range(sheet_name, f"A{DATA_START_ROW}:H5000")
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


def map_ebay_item_id_to_row_and_url(sheet_name: str = SHEET_NAME) -> dict[str, dict]:
    """
    A列=eBay Item ID をキーに、行番号・D列メルカリURL・F列status を返す。
    read_all_items は D 空欄をスキップするが、本関数は A 列がある行をすべて読む（SKU 補完用）。
    """
    service = _get_service()
    range_name = _a1_range(sheet_name, f"A{DATA_START_ROW}:H5000")
    req = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=range_name)
    result = _retry_api_call(req.execute)
    rows = result.get("values", [])
    out: dict[str, dict] = {}
    for i, row in enumerate(rows):
        while len(row) < 8:
            row.append("")
        eid = row[COL_EBAY_ITEM_ID].strip() if COL_EBAY_ITEM_ID < len(row) else ""
        if not eid:
            continue
        if eid in out:
            logger.warning("在庫管理表: A列 Item ID 重複 %s (行 %s は上書き)", eid, DATA_START_ROW + i)
        murl = row[COL_MERCARI_URL].strip() if COL_MERCARI_URL < len(row) else ""
        st = row[COL_STATUS].strip() if COL_STATUS < len(row) else ""
        out[eid] = {
            "row": DATA_START_ROW + i,
            "mercari_url": murl,
            "status": st,
        }
    return out


def update_item_status(row: int, status: str, sheet_name: str = SHEET_NAME) -> None:
    """
    特定行のステータスを更新する
    """
    service = _get_service()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    values = [[status]]
    # 規約: A=URL, B=Profit, C=Price, D=ItemID, E=Status
    is_listing_sheet = _is_listing_queue_sheet(sheet_name)
    col_letter = "E" if is_listing_sheet else "D"
    range_name = _a1_range(sheet_name, f"{col_letter}{row}")

    req = service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=range_name,
        valueInputOption="RAW",
        body={"values": values}
    )
    _retry_api_call(req.execute)

    logger.info(
        f"行 {row} → ステータス: {status} (シート={_norm_sheet_title(sheet_name)!r}, "
        f"出品キュー={is_listing_sheet}, 列={col_letter}), 更新日時: {now}"
    )


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
            "range": _a1_range(s_name, f"F{row}"),
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
    want = _norm_sheet_title(sheet_name)
    for sheet in sheets:
        if _norm_sheet_title(sheet.get("properties", {}).get("title", "")) == want:
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


def append_queue_dead_to_inventory(mercari_url: str, reason: str) -> None:
    """
    出品待ちから取り除いた「メルカリで既に購入不可」の行を、在庫管理表に記録する（未eBay出品分）。
    在庫チェック対象は通常 Active かつ ItemID ありのみなので、ステータスで区別する。
    """
    service = _get_service()
    row_data = [""] * 8
    row_data[COL_MERCARI_URL] = mercari_url
    row_data[COL_STATUS] = "ENDED_メルカリ売切_未出品"
    if COL_NOTES >= 0:
        row_data[COL_NOTES] = (reason or "")[:500]
    req = service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=_a1_range(SHEET_NAME, "A1:H1"),
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row_data]},
    )
    _retry_api_call(req.execute)
    logger.info(f"在庫管理表にキュー除外を記録: {mercari_url[:60]}...")


def _load_sold_urls_from_items_csv() -> set[str]:
    """items.csv の mercari_url / SOLD_URL 列（SOLD 記録済みURL）。"""
    import csv
    import os

    sold: set[str] = set()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "items.csv")
    if not os.path.exists(path):
        return sold
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for key in ("mercari_url", "SOLD_URL"):
                url = row.get(key, "").strip()
                if url:
                    sold.add(url)
    return sold


def purge_items_csv_sold_from_queue_rows() -> dict:
    """
    items.csv に既に SOLD 記録があるのに、優先/自動出品シートの「出品待ち」に残っている行を削除する。
    record_sold 等で CSV に入ったがシート行が残ったケースを整理し、sold_urls テストを通す。
    """
    from config import PRIORITY_SHEET_NAME, AUTO_SHEET_NAME, AUTO_SHEETS

    sold_urls = _load_sold_urls_from_items_csv()
    stats = {"checked": 0, "removed": 0, "by_sheet": {}}
    if not sold_urls:
        logger.info("purge_items_csv_sold_from_queue_rows: items.csv に SOLD URL なし — スキップ")
        return stats

    listing_sheet_names = [PRIORITY_SHEET_NAME, AUTO_SHEET_NAME] + list(AUTO_SHEETS)
    service = _get_service()

    for s_name in listing_sheet_names:
        try:
            req = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID,
                range=_a1_range(s_name, "A2:F3000"),
            )
            res = _retry_api_call(req.execute)
        except Exception as e:
            logger.warning(f"purge_items_csv_sold: 読み込みスキップ {s_name}: {e}")
            continue

        values = res.get("values", [])
        rows_to_delete: list[int] = []
        for i, row in enumerate(values):
            while len(row) < 6:
                row.append("")
            if not row[0].strip():
                continue
            status = row[4].strip() if len(row) > 4 else ""
            if "出品済み" in status or "⛔" in status or "❌" in status:
                continue
            url = row[0].strip()
            stats["checked"] += 1
            if url in sold_urls:
                rows_to_delete.append(DATA_START_ROW + i)

        if rows_to_delete:
            delete_rows(s_name, rows_to_delete)
            stats["removed"] += len(rows_to_delete)
            stats["by_sheet"][s_name] = len(rows_to_delete)

    logger.info(
        f"purge_items_csv_sold_from_queue_rows: 出品待ちチェック {stats['checked']} 行, "
        f"items.csv SOLD 重複を {stats['removed']} 行削除 {stats['by_sheet']}"
    )
    return stats


def purge_unbuyable_queue_rows() -> dict:
    """
    優先出品・自動出品系シートの「出品待ち」行について、メルカリが sold_out / deleted / auction
    のものを行削除し、items.csv に SOLD 記録、在庫管理表に履歴1行追加する。
    test_rules / auto_lister 前に呼び出し、売切り放置で全体停止しないようにする。
    """
    from mercari_checker import check_mercari_status
    from sold_tracker import record_sold
    from config import PRIORITY_SHEET_NAME, AUTO_SHEET_NAME, AUTO_SHEETS

    listing_sheet_names = [PRIORITY_SHEET_NAME, AUTO_SHEET_NAME] + list(AUTO_SHEETS)
    stats = {"checked": 0, "removed": 0, "by_sheet": {}}
    service = _get_service()

    for s_name in listing_sheet_names:
        try:
            req = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID,
                range=_a1_range(s_name, "A2:F3000"),
            )
            res = _retry_api_call(req.execute)
        except Exception as e:
            logger.warning(f"purge_unbuyable: 読み込みスキップ {s_name}: {e}")
            continue

        values = res.get("values", [])
        rows_to_delete: list[int] = []
        for i, row in enumerate(values):
            while len(row) < 6:
                row.append("")
            if not row[0].strip():
                continue
            status = row[4].strip() if len(row) > 4 else ""
            if "出品済み" in status or "⛔" in status or "❌" in status:
                continue
            url = row[0].strip()
            stats["checked"] += 1
            result = check_mercari_status(url, delay=0.7)
            st = result.get("status", "error")
            if st in ("sold_out", "deleted", "auction"):
                try:
                    record_sold(url, "", f"queue_purge:{st}")
                except Exception as e:
                    logger.warning(f"record_sold 失敗（続行） {url}: {e}")
                try:
                    append_queue_dead_to_inventory(url, f"出品待ちから自動移動 ({s_name}) mercari={st}")
                except Exception as e:
                    logger.warning(f"在庫管理への記録失敗（続行） {url}: {e}")
                rows_to_delete.append(DATA_START_ROW + i)

        if rows_to_delete:
            delete_rows(s_name, rows_to_delete)
            stats["removed"] += len(rows_to_delete)
            stats["by_sheet"][s_name] = len(rows_to_delete)

    logger.info(
        f"purge_unbuyable_queue_rows: チェック {stats['checked']} 行, 削除 {stats['removed']} 行 {stats['by_sheet']}"
    )
    return stats


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
        range=_a1_range(SHEET_NAME, "A1:H1"),
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body
    )
    _retry_api_call(req.execute)
    logger.info(f"在庫管理表に新しい商品を追加しました: {ebay_item_id} / {mercari_url}")


def ensure_mercari_oos_review_sheet(sheet_name: str) -> None:
    """メルカリ在庫 ambiguous 用「要確認」タブ。無ければ作成しヘッダのみ設定。"""
    name = _norm_sheet_title(sheet_name)
    if not name:
        return
    service = _get_service()
    try:
        req = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID, ranges=[_a1_range(name, "A1")])
        _retry_api_call(req.execute)
        return
    except Exception:
        pass
    body = {"requests": [{"addSheet": {"properties": {"title": name}}}]}
    req_create = service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=body)
    _retry_api_call(req_create.execute)
    headers = [["記録日時", "メルカリURL", "eBayItemID", "理由"]]
    req_header = service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=_a1_range(name, "A1:D1"),
        valueInputOption="RAW",
        body={"values": headers},
    )
    _retry_api_call(req_header.execute)
    logger.info("シート '%s' を作成（メルカリ要確認用）", name)


def append_mercari_ambiguous_review_row(
    mercari_url: str,
    ebay_item_id: str,
    reason: str,
    sheet_name: str,
) -> None:
    """段階4: ambiguous を要確認シートへ（eBay は触らない）。"""
    ensure_mercari_oos_review_sheet(sheet_name)
    service = _get_service()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [[ts, mercari_url, ebay_item_id, (reason or "")[:900]]]
    req = service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=_a1_range(sheet_name, "A1:D1"),
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": row},
    )
    _retry_api_call(req.execute)
    logger.info("要確認シート追記: eBay=%s reason=%s", ebay_item_id, (reason or "")[:120])


def create_sheet_if_not_exists(sheet_name: str) -> None:
    """シートが存在しない場合に新規作成する"""
    service = _get_service()
    try:
        req = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID, ranges=[_a1_range(sheet_name, "A1")])
        _retry_api_call(req.execute)
    except Exception:
        logger.info(f"シート '{sheet_name}' を作成中...")
        body = {"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}
        req_create = service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=body)
        _retry_api_call(req_create.execute)
        # ヘッダー (A=URL, B=Price, C=ItemID, D=Status)
        headers = [["メルカリURL", "出品価格($)", "eBayItemID", "Status", "Notes"]]
        req_header = service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID, range=_a1_range(sheet_name, "A1"),
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
