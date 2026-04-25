#!/usr/bin/env python3
"""
在庫管理表のメルカリ URL から仕入価格(円)を取得し「仕入価格(JPY)」列に書き込む。

- Google Sheets API は sheets_manager のヘルパーのみ利用（sheets_manager 本体は変更しない）
- スプレッドシート ID は本スクリプト内の定数（config の SPREADSHEET_ID とは別）
- メルカリ取得は Playwright + ページ内 JS（mercari_scraper の価格抽出パターンを参考に独立実装）
"""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# 在庫管理表（依頼仕様の専用ブック・シート）
INVENTORY_SPREADSHEET_ID = "1RfNtaqyzjpiwD4LqLbD_cPIGTj62cUorfKywPYtJ128"
INVENTORY_SHEET_NAME = "在庫管理表1"
PURCHASE_HEADER = "仕入価格(JPY)"
# A=ItemID, B=商品名, C=仕入先, D=URL, E=在庫状況, F=Status, G=在庫切れ時の対応 → H=仕入価格(既定)
MIN_PURCHASE_COL_INDEX = 7  # 0-based → H 列
LOCK_PATH = "/tmp/mercari_access.lock"

# メルカリ商品ページから価格(整数円)を返す JS（mercari_scraper の getPrice 相当を簡略化）
_EXTRACT_PRICE_JS = r"""() => {
  const meta = document.querySelector('meta[property="product:price:amount"]');
  if (meta && meta.content) {
    const n = parseInt(meta.content, 10);
    if (!isNaN(n) && n > 0) return n;
  }
  const selectors = [
    '[data-testid="price"]',
    'span[class*="price"]',
    'mer-price',
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el && el.innerText) {
      const num = el.innerText.replace(/[^0-9]/g, '');
      if (num && parseInt(num, 10) > 0) return parseInt(num, 10);
    }
  }
  const scripts = document.querySelectorAll('script[type="application/ld+json"]');
  for (const s of scripts) {
    try {
      const j = JSON.parse(s.textContent);
      if (j.offers && j.offers.price) {
        const p = parseInt(String(j.offers.price), 10);
        if (!isNaN(p) && p > 0) return p;
      }
      if (j.price) {
        const p = parseInt(String(j.price), 10);
        if (!isNaN(p) && p > 0) return p;
      }
    } catch (e) {}
  }
  return 0;
}"""


def col_index_to_a1(col_0based: int) -> str:
    """0-based 列インデックスを A1 記法の列文字へ（A=0 … Z=25、AA 以降も対応）。"""
    n = col_0based + 1
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def normalize_header_cell(s: str) -> str:
    return (s or "").strip()


def find_purchase_column_index(header_row: list[str]) -> int | None:
    """ヘッダー行から「仕入価格(JPY)」列の 0-based インデックス。無ければ None。"""
    for i, cell in enumerate(header_row):
        h = normalize_header_cell(cell)
        if h == PURCHASE_HEADER or h == "仕入価格（JPY）":
            return i
    return None


def compute_new_purchase_column_index(header_row: list[str]) -> int:
    """新規列の 0-based インデックス: max(H列相当, ヘッダー右端の次列)。"""
    n = len(header_row)
    while n > 0 and normalize_header_cell(header_row[n - 1]) == "":
        n -= 1
    return max(MIN_PURCHASE_COL_INDEX, n)


@dataclass
class ConsecutiveErrorTracker:
    count: int = 0

    def on_success(self) -> None:
        self.count = 0

    def on_failure(self) -> bool:
        """True を返したら呼び出し側が sleep(60) すべき。False で継続。"""
        self.count += 1
        return self.count == 5

    def should_abort(self) -> bool:
        return self.count >= 10


class MercariAccessLock:
    """fcntl による /tmp/mercari_access.lock 排他（Windows では何もしない）。"""

    def __init__(self, path: str = LOCK_PATH, ignore: bool = False) -> None:
        self.path = path
        self.ignore = ignore
        self._fd: int | None = None

    def __enter__(self) -> MercariAccessLock:
        if self.ignore:
            return self
        if os.name == "nt":
            logger.warning("Windows のためロックをスキップします")
            return self
        self._fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self._fd)
            self._fd = None
            raise RuntimeError(f"ロック取得失敗: {self.path}（他プロセスが使用中）") from None
        os.write(self._fd, f"{os.getpid()}\n".encode())
        return self

    def __exit__(self, *args: Any) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None


def read_header_row(service: Any, spreadsheet_id: str, sheet: str) -> list[str]:
    from sheets_manager import _retry_api_call

    rng = f"{sheet}!A1:Z1"
    req = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=rng)
    res = _retry_api_call(req.execute)
    row = (res.get("values") or [[]])[0]
    return list(row)


def read_data_rows(
    service: Any, spreadsheet_id: str, sheet: str, last_col_letter: str, start_row: int = 2, max_row: int = 5000
) -> list[list[str]]:
    from sheets_manager import _retry_api_call

    rng = f"{sheet}!A{start_row}:{last_col_letter}{max_row}"
    req = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=rng)
    res = _retry_api_call(req.execute)
    return res.get("values") or []


def update_cell(
    service: Any,
    spreadsheet_id: str,
    sheet: str,
    row_1based: int,
    col_0based: int,
    value: str,
    *,
    dry_run: bool,
) -> None:
    col = col_index_to_a1(col_0based)
    rng = f"{sheet}!{col}{row_1based}"
    from sheets_manager import _retry_api_call

    if dry_run:
        logger.info("[dry-run] 書き込み予定: %s = %s", rng, value)
        return
    req = service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=rng,
        valueInputOption="RAW",
        body={"values": [[value]]},
    )
    _retry_api_call(req.execute)


def fetch_price_playwright(
    url: str, *, fetch_impl: Callable[[str], tuple[int | None, str | None]] | None = None
) -> tuple[int | None, str | None]:
    """
    メルカリ商品ページから価格を取得。

    Returns:
        (price_jpy or None, error_message or None)
    """
    if fetch_impl is not None:
        return fetch_impl(url)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "playwright が import できません"

    u = (url or "").strip()
    if not u or "mercari" not in u.lower():
        return None, "メルカリ URL ではありません"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                locale="ja-JP",
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            try:
                resp = page.goto(u, wait_until="domcontentloaded", timeout=45_000)
                if resp is not None and resp.status == 404:
                    return None, "404"
                title = page.title()
                if "ページが見つかりません" in title or "404" in title:
                    return None, "404"
                time.sleep(0.5)
                price = int(page.evaluate(_EXTRACT_PRICE_JS))
                if price <= 0:
                    return None, "価格取得失敗(0)"
                return price, None
            finally:
                page.close()
                context.close()
        finally:
            browser.close()


def run(
    *,
    dry_run: bool,
    limit: int | None,
    fetch_impl: Callable[[str], tuple[int | None, str | None]] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    get_service: Callable[[], Any] | None = None,
) -> None:
    _sleep = sleep_fn or time.sleep
    if get_service is None:
        from sheets_manager import _get_service

        get_service = _get_service
    service = get_service()

    logger.info("在庫管理表 %s を読み込み中...", INVENTORY_SHEET_NAME)
    header = read_header_row(service, INVENTORY_SPREADSHEET_ID, INVENTORY_SHEET_NAME)
    while len(header) < MIN_PURCHASE_COL_INDEX + 1:
        header.append("")

    pidx = find_purchase_column_index(header)
    if pidx is None:
        pidx = compute_new_purchase_column_index(header)
        logger.info("「%s」列が無いため列 %s に追加します", PURCHASE_HEADER, col_index_to_a1(pidx))
        if not dry_run:
            update_cell(
                service,
                INVENTORY_SPREADSHEET_ID,
                INVENTORY_SHEET_NAME,
                1,
                pidx,
                PURCHASE_HEADER,
                dry_run=False,
            )
        elif dry_run:
            logger.info("[dry-run] ヘッダー追加予定: %s1 = %s", col_index_to_a1(pidx), PURCHASE_HEADER)

    last_col_idx = max(pidx, MIN_PURCHASE_COL_INDEX, len(header) - 1)
    last_letter = col_index_to_a1(last_col_idx)
    rows = read_data_rows(service, INVENTORY_SPREADSHEET_ID, INVENTORY_SHEET_NAME, last_letter)

    pending: list[tuple[int, str, str]] = []  # (sheet_row, item_id, url)
    for i, row in enumerate(rows):
        sheet_row = 2 + i
        while len(row) <= max(3, pidx):
            row.append("")
        url = normalize_header_cell(row[3])
        if not url or "mercari" not in url.lower():
            continue
        existing = normalize_header_cell(row[pidx]) if pidx < len(row) else ""
        if existing:
            continue
        item_id = normalize_header_cell(row[0]) if len(row) > 0 else ""
        pending.append((sheet_row, item_id, url))

    total_unfetched = len(pending)
    if limit is not None:
        pending = pending[: max(0, limit)]

    logger.info("価格未取得の行: %s件 / %s件中", len(pending), total_unfetched)

    tracker = ConsecutiveErrorTracker()
    ok_count = 0
    fail_count = 0
    skip_count = 0

    for n, (sheet_row, item_id, url) in enumerate(pending, start=1):
        logger.info("[%s/%s] ItemID=%s, URL=%s", n, len(pending), item_id or "—", url)
        price, err = fetch_price_playwright(url, fetch_impl=fetch_impl)
        if price is not None:
            logger.info("[%s/%s] 価格取得成功: ¥%s", n, len(pending), f"{int(price):,}")
            update_cell(
                service,
                INVENTORY_SPREADSHEET_ID,
                INVENTORY_SHEET_NAME,
                sheet_row,
                pidx,
                str(int(price)),
                dry_run=dry_run,
            )
            tracker.on_success()
            ok_count += 1
            _sleep(1.2)
            continue

        msg = err or "不明"
        if msg == "404":
            logger.warning("[%s/%s] ページが見つかりません(404)、スキップ", n, len(pending))
        else:
            logger.warning("[%s/%s] 取得失敗: %s、スキップ", n, len(pending), msg)
        fail_count += 1
        if tracker.on_failure():
            logger.warning("連続エラー 5 回 — 60 秒待機します")
            _sleep(60)
        if tracker.should_abort():
            logger.error("連続エラー 10 回 — スクリプトを停止します")
            sys.exit(2)
        _sleep(1.2)

    logger.info("完了: 取得成功 %s件 / 失敗 %s件 / スキップ %s件", ok_count, fail_count, skip_count)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
        stream=sys.stdout,
    )
    ap = argparse.ArgumentParser(description="在庫管理表の仕入価格(JPY)をメルカリから取得して書き込む")
    ap.add_argument("--dry-run", action="store_true", help="スプレッドシートに書き込まない")
    ap.add_argument("--limit", type=int, default=None, metavar="N", help="処理する最大件数")
    ap.add_argument(
        "--ignore-lock",
        action="store_true",
        help="ロックを取得しない（Mac ローカル試験用。本番 VPS では付けないこと）",
    )
    args = ap.parse_args(argv)

    try:
        with MercariAccessLock(ignore=args.ignore_lock):
            run(dry_run=args.dry_run, limit=args.limit)
    except RuntimeError as e:
        logger.error("%s", e)
        sys.exit(1)
    except HttpError as e:
        logger.error("Google Sheets API エラー: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
