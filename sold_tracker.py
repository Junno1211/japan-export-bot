"""
sold_tracker.py — SOLD商品の永久追跡
eBayで売れた商品を items.csv に SOLD として記録し、
全リストックスクリプトが2重販売を防止できるようにする。
"""

import csv
import os
import logging
import fcntl
from typing import Set

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ITEMS_CSV = os.path.join(_BASE_DIR, "items.csv")
_FIELDNAMES = ["mercari_url", "ebay_item_id", "memo", "status"]


def _read_all_rows() -> list[dict]:
    if not os.path.exists(ITEMS_CSV):
        return []
    with open(ITEMS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def get_sold_urls() -> Set[str]:
    """SOLD状態の全メルカリURLを返す"""
    return {
        row["mercari_url"].strip()
        for row in _read_all_rows()
        if row.get("status", "").upper() == "SOLD"
        and row.get("mercari_url", "").strip()
    }


def get_sold_ebay_ids() -> Set[str]:
    """SOLD状態の全eBay Item IDを返す"""
    return {
        row["ebay_item_id"].strip()
        for row in _read_all_rows()
        if row.get("status", "").upper() == "SOLD"
        and row.get("ebay_item_id", "").strip()
    }


def is_sold(mercari_url: str = "", ebay_item_id: str = "") -> bool:
    """指定のメルカリURLまたはeBay IDがSOLD済みかチェック"""
    rows = _read_all_rows()
    for row in rows:
        if mercari_url and row.get("mercari_url", "").strip() == mercari_url.strip():
            if row.get("status", "").upper() == "SOLD":
                return True
        if ebay_item_id and row.get("ebay_item_id", "").strip() == ebay_item_id.strip():
            if row.get("status", "").upper() == "SOLD":
                return True
    return False


def record_sold(mercari_url: str, ebay_item_id: str, memo: str = ""):
    """商品をSOLDとして永久記録する（既存行を更新 or 新規追加）"""
    rows = _read_all_rows()
    found = False

    for row in rows:
        if (mercari_url and row.get("mercari_url", "").strip() == mercari_url.strip()) or \
           (ebay_item_id and row.get("ebay_item_id", "").strip() == ebay_item_id.strip()):
            row["status"] = "SOLD"
            found = True

    if not found:
        rows.append({
            "mercari_url": mercari_url,
            "ebay_item_id": ebay_item_id,
            "memo": memo,
            "status": "SOLD",
        })

    # ファイルロック付き書き込み
    with open(ITEMS_CSV, "w", encoding="utf-8", newline="") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        fcntl.flock(f, fcntl.LOCK_UN)

    logger.info(f"SOLD記録完了: {mercari_url} / eBay {ebay_item_id}")
