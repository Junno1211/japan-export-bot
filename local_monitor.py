#!/usr/bin/env python3
import time
import logging
import sys
from datetime import datetime
from main import run

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def start_daemon(interval_minutes=60):
    logger.info(f"🟢 ローカル自動巡回プロセスを起動しました。設定間隔: {interval_minutes}分")
    
    while True:
        try:
            logger.info("🕒 定期巡回（自動スクレイピング＆eBay同期）を開始します...")
            run(dry_run=False)
        except Exception as e:
            logger.error(f"巡回中に予期せぬ重大エラーが発生しました: {e}")
            
        next_run = datetime.now().timestamp() + (interval_minutes * 60)
        logger.info(f"💤 次回の巡回まで {interval_minutes} 分待機します...")
        
        # キャンセル（Ctrl+C）を受け付けつつスリープ
        try:
            time.sleep(interval_minutes * 60)
        except KeyboardInterrupt:
            logger.info("🛑 自動巡回プロセスを終了します。")
            break

if __name__ == "__main__":
    # デフォルトは30分ごとの巡回
    start_daemon(30)
