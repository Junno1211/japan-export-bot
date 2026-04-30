#!/usr/bin/env python3
"""
eBay Active かつ quantity=0 のうち、メルカリ URL が解決できる行を最大 N 件検査し、
メルカリ実ページに「購入手続みへ」がある（Playwright・safe_restock と同系）ときだけ
eBay を数量 1 に戻す。

背景:
  ebay_restock_all.py は (1) メルカリ公式 API のみ (2) SKU に URL/m が無いと対象外。
  在庫管理の誤 OOS は items.csv に SOLD が付いていることが多い → --ignore-sold-csv が必要な場合あり。

使い方（必ず VPS・本番 .env）:
  cd /opt/export-bot
  ./venv/bin/python3 -u scripts/repair_false_ebay_oos_vs_mercari.py --dry-run --limit 500
  ./venv/bin/python3 -u scripts/repair_false_ebay_oos_vs_mercari.py --apply --limit 500 --ignore-sold-csv

注意:
  Playwright は直列（1 URL ずつ）。500 件は数時間かかることがあります。
  二重販売防止のため、メルカリが active でない限り eBay は触りません。
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("repair_false_oos")

from config import COL_STATUS, SHEET_NAME, SPREADSHEET_ID  # noqa: E402
from ebay_updater import get_all_active_list_items, set_quantity  # noqa: E402
from mercari_checker import check_stock_by_purchase_button  # noqa: E402
from sheets_manager import _a1_range, _get_service, _retry_api_call, map_ebay_item_id_to_row_and_url  # noqa: E402
from sold_tracker import get_sold_ebay_ids  # noqa: E402


# quantity は 0 が有効値のため `int(x.get("quantity") or -1)` は禁止（0 or -1 → -1）。
def _parse_quantity(r: dict, key: str = "quantity") -> int:
    v = r.get(key)
    if v is None:
        return -1
    try:
        return int(v)
    except (TypeError, ValueError):
        return -1


def _mercari_url_from_sku(sku: str) -> str:
    s = (sku or "").strip()
    if not s:
        return ""
    sl = s.lower()
    if "mercari" in sl and (s.startswith("http://") or s.startswith("https://")):
        return s
    if re.match(r"^m\d+$", s, re.I):
        return f"https://jp.mercari.com/item/{s}"
    return ""


def _resolve_url_and_row(ebay_id: str, sku: str, sheet_map: dict) -> tuple[str, int | None]:
    url = _mercari_url_from_sku(sku)
    row = sheet_map.get(ebay_id, {}).get("row")
    if not url or "mercari" not in url.lower():
        info = sheet_map.get(ebay_id)
        if info:
            cand = (info.get("mercari_url") or "").strip()
            if cand and "mercari" in cand.lower():
                url = cand
                row = info.get("row")
    return (url.strip(), row)


def _sort_ebay_ids_recent_first(rows: list[dict]) -> list[dict]:
    """Item ID の数値降順を「概ね新しい順」の代理にする。"""

    def key(r: dict) -> int:
        try:
            return int((r.get("item_id") or "0").strip())
        except ValueError:
            return 0

    return sorted(rows, key=key, reverse=True)


def _write_report(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fieldnames = ["ebay_id", "mercari_url", "sheet_row", "html_status", "action"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    logger.info("レポート: %s", path)


def _set_sheet_active(row: int | None) -> None:
    if row is None:
        return
    status_col = chr(65 + COL_STATUS)
    service = _get_service()
    rng = _a1_range(SHEET_NAME, f"{status_col}{row}")
    req = service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=rng,
        valueInputOption="USER_ENTERED",
        body={"values": [["Active"]]},
    )
    _retry_api_call(req.execute)
    logger.info("シート %s 行 %s → Active", SHEET_NAME, row)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="eBay在庫0×メルカリ実ページ(購入可)の不一致を検査し、必要なら eBay を1に戻す",
    )
    ap.add_argument("--limit", type=int, default=500, help="検査する在庫0件数の上限（既定500）")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="eBay / シートは更新せずログとレポートのみ",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="メルカリ購入可のとき eBay を1にし、シートを Active に戻す",
    )
    ap.add_argument(
        "--ignore-sold-csv",
        action="store_true",
        help="items.csv の SOLD を無視（誤記録の復旧用。HTMLで購入可のときだけ Revise）",
    )
    ap.add_argument(
        "--no-fix-sheet",
        action="store_true",
        help="eBay だけ戻し、在庫管理表 F 列は触らない",
    )
    ap.add_argument(
        "--delay",
        type=float,
        default=0.35,
        help="Playwright 各件の前待ち秒（既定0.35）",
    )
    args = ap.parse_args()

    if args.dry_run and args.apply:
        logger.error("--dry-run と --apply は同時に指定しないでください")
        return 2
    if not args.dry_run and not args.apply:
        logger.error("--dry-run か --apply のどちらかを指定してください")
        return 2

    sold_ids = set()
    if not args.ignore_sold_csv:
        sold_ids = get_sold_ebay_ids()
        logger.info("items.csv SOLD の eBay ID はスキップ: %s 件", len(sold_ids))
    else:
        logger.info("--ignore-sold-csv: CSV の SOLD を条件に使いません")

    logger.info("eBay Active 一覧取得中…")
    active = get_all_active_list_items()
    zero = [r for r in active if _parse_quantity(r) == 0]
    zero = _sort_ebay_ids_recent_first(zero)
    logger.info("Active かつ quantity=0: %s 件（全件）", len(zero))

    logger.info("在庫管理表マップ取得中…")
    sheet_map = map_ebay_item_id_to_row_and_url(SHEET_NAME)

    candidates: list[tuple[str, str, int | None]] = []
    for r in zero:
        eid = (r.get("item_id") or "").strip()
        sku = (r.get("sku") or "").strip()
        if not eid:
            continue
        if not args.ignore_sold_csv and eid in sold_ids:
            continue
        url, row = _resolve_url_and_row(eid, sku, sheet_map)
        if not url:
            continue
        candidates.append((eid, url, row))

    cap = max(1, args.limit)
    candidates = candidates[:cap]
    logger.info("検査対象: %s 件（--limit=%s 適用後）", len(candidates), cap)

    report_rows: list[dict] = []
    restored = 0
    skipped_html = 0

    for i, (ebay_id, url, row) in enumerate(candidates, start=1):
        logger.info("[%s/%s] eBay=%s HTML確認…", i, len(candidates), ebay_id)
        hres = check_stock_by_purchase_button(url, delay=args.delay)
        st = hres.get("status", "")
        action = "skip"
        if st == "active":
            if args.apply:
                res = set_quantity(ebay_id, 1)
                if res.get("success"):
                    restored += 1
                    action = "restored_ebay_qty_1"
                    if not args.no_fix_sheet:
                        try:
                            _set_sheet_active(row)
                        except Exception as ex:
                            logger.warning("シート Active 更新失敗（eBay は復旧済）: %s", ex)
                else:
                    action = f"ebay_fail:{res.get('message', '')[:200]}"
                    logger.warning("eBay Revise 失敗 %s: %s", ebay_id, res.get("message"))
            else:
                action = "would_restore"
        else:
            skipped_html += 1
            action = f"skip_html:{st}"
            logger.info("  SKIP メルカリ status=%s (%s)", st, url[:60])

        report_rows.append(
            {
                "ebay_id": ebay_id,
                "mercari_url": url,
                "sheet_row": row or "",
                "html_status": st,
                "action": action,
            }
        )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rep_path = os.path.join(ROOT, "logs", f"repair_false_oos_report_{ts}.csv")
    _write_report(rep_path, report_rows)

    mode = "DRY-RUN" if args.dry_run else "APPLY"
    would_n = sum(1 for x in report_rows if x.get("action") == "would_restore")
    done_msg = f"復旧 {restored} 件" if args.apply else f"復旧候補 {would_n} 件（--apply で実行）"
    logger.info(
        "🏁 %s 終了: メルカリ購入可で %s / HTMLで非activeスキップ %s / レポート %s",
        mode,
        done_msg,
        skipped_html,
        rep_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
