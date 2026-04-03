#!/usr/bin/env python3
# ============================================================
#  main.py  —  メルカリ在庫監視 → eBay出品自動取り消し
# ============================================================

import argparse
import logging
import sys
import os
import fcntl
from datetime import datetime

from config import REQUEST_DELAY_SEC, SHEET_NAME

# ---- 二重起動防止 -------------------------------------------
LOCK_FILE = os.path.join(os.path.dirname(__file__), ".main_lock")

def acquire_lock():
    """ロックファイルで二重起動を防ぐ。取得できなければ即終了。"""
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_fd
    except BlockingIOError:
        print("別のmain.pyプロセスが実行中です。終了します。")
        sys.exit(0)
from mercari_checker import check_mercari_status
from ebay_updater import mark_out_of_stock
from notifier import notify_slack
from sheets_manager import read_active_items, batch_update_statuses, delete_rows

# ---- ロギング設定 -------------------------------------------
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            f"logs/monitor_{datetime.now().strftime('%Y%m%d')}.log",
            encoding="utf-8"
        )
    ]
)
logger = logging.getLogger(__name__)


# ============================================================
def run(dry_run: bool = False) -> None:
    start = datetime.now()
    logger.info("=" * 60)
    logger.info(f"🚀 監視開始: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    if dry_run:
        logger.info("⚠️  DRY RUN モード（eBay取り消しはしない）")
    logger.info("=" * 60)

    try:
        items = read_active_items()
    except Exception as e:
        logger.error(f"Google Sheetsからのデータ取得に失敗しました: {e}")
        notify_slack("🛑 Google Sheets読み込みエラーが発生しました！")
        sys.exit(1)

    cancelled = 0
    errors = 0
    updates = []
    rows_to_delete = []

    for i, item in enumerate(items):
        url = item["mercari_url"]
        ebay_id = item.get("ebay_item_id", "")
        row_id = item["row"]
        mercari_id = item.get("mercari_id", "")

        logger.info(f"\n[{i+1}/{len(items)}] Row:{row_id} | eBay:{ebay_id}")
        logger.info(f"  メルカリ: {url}")

        if not ebay_id:
            logger.warning(f"  ⚠️ eBay IDなし — スキップ")
            continue

        result = check_mercari_status(url, delay=REQUEST_DELAY_SEC)
        status = result["status"]
        title = result.get("title", "")

        if status == "active":
            logger.info(f"  ✅ 在庫あり: {title[:50]}")
            updates.append({"row": row_id, "status": "Active", "notes": ""})

        elif status in ("sold_out", "deleted"):
            logger.info(f"  ❌ 売り切れ検知: {title[:50]}")

            if not dry_run:
                ebay_result = mark_out_of_stock(ebay_id)
                if ebay_result["success"]:
                    logger.info(f"  ✅ eBay在庫0に更新完了: {ebay_id}")
                    cancelled += 1
                    # 社長のご要望により、在庫0時のSlack通知はOFFにしました
                    # notify_slack(f"🛑 eBay在庫0: {ebay_id} / {mercari_id}\nメルカリ売り切れ → eBay在庫を0にしました")
                    # シートにステータスを書かず、削除対象にする
                    rows_to_delete.append(row_id)
                else:
                    logger.error(f"  ❌ eBay更新失敗: {ebay_id} / {ebay_result['message']}")
                    errors += 1
                    updates.append({"row": row_id, "status": "Active", "notes": f"eBay API Error: {ebay_result['message']}"})
            else:
                logger.info(f"  [DRY RUN] eBay取り消しをスキップ: {ebay_id}")
                cancelled += 1
                updates.append({"row": row_id, "status": "Active", "notes": "DRY RUN - Sold out detected"})

        elif status == "auction":
            logger.warning(f"  ⛔ オークション変更検出: {title[:50]} → eBay {ebay_id} 在庫0")
            if not dry_run:
                ebay_result = mark_out_of_stock(ebay_id)
                if ebay_result["success"]:
                    logger.info(f"  ✅ eBay在庫0完了(オークション): {ebay_id}")
                    cancelled += 1
                    rows_to_delete.append(row_id)
                else:
                    logger.error(f"  ❌ eBay更新失敗(オークション): {ebay_id} / {ebay_result['message']}")
                    errors += 1

        elif status == "error":
            logger.warning(f"  ⚠️ チェックエラー: {result.get('error', '')}")
            errors += 1
            updates.append({"row": row_id, "status": "Active", "notes": f"Check Error: {result.get('error', '')}"})

    if not dry_run and updates:
        try:
            batch_update_statuses(updates)
            logger.info("✅ Google Sheetsへの一括ステータス更新が完了しました")
        except Exception as e:
            logger.error(f"Google Sheetsの更新に失敗しました: {e}")
            
    if not dry_run and rows_to_delete:
        try:
            logger.info(f"🗑️ 売り切れ処理の済んだ {len(rows_to_delete)} 件の行をシートから削除します...")
            delete_rows(SHEET_NAME, rows_to_delete)
        except Exception as e:
            logger.error(f"Google Sheetsの行削除に失敗しました: {e}")

    elapsed = (datetime.now() - start).seconds
    logger.info("\n" + "=" * 60)
    logger.info(f"✅ 完了: {elapsed}秒")
    logger.info(f"   チェック件数    : {len(items)}")
    logger.info(f"   eBay取り消し    : {cancelled}")
    logger.info(f"   エラー          : {errors}")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="eBay取り消しおよびシート更新をせずにテスト実行")
    parser.add_argument("--check", type=str, default=None,
                        help="特定メルカリURLだけチェック")
    parser.add_argument("--loop", action="store_true",
                        help="常駐モード: 15分間隔で在庫チェックを繰り返す")
    parser.add_argument("--interval", type=int, default=900,
                        help="ループ間隔（秒）。デフォルト900秒=15分")
    args = parser.parse_args()

    lock_fd = acquire_lock()

    # === test_rules.py ゲート ===
    import subprocess
    _test_result = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(__file__), "test_rules.py")],
        capture_output=True, text=True, timeout=120
    )
    if _test_result.returncode != 0:
        logger.error("🚨 test_rules.py 失敗 — main.py 起動中止")
        logger.error(_test_result.stdout[-500:] if _test_result.stdout else "")
        notify_slack("🚨 test_rules.py 失敗 — main.py 起動中止")
        sys.exit(1)
    logger.info("✅ test_rules.py 全テスト合格")

    if args.check:
        from mercari_checker import check_mercari_status
        result = check_mercari_status(args.check, delay=0)
        print(f"結果: {result}")
    elif args.loop:
        import time as _time
        logger.info(f"🔁 常駐モード開始（間隔: {args.interval}秒）")
        while True:
            try:
                run(dry_run=args.dry_run)
            except Exception as e:
                logger.error(f"ループ内エラー（継続します）: {e}")
            logger.info(f"💤 次回チェックまで {args.interval}秒 待機...")
            _time.sleep(args.interval)
    else:
        run(dry_run=args.dry_run)
