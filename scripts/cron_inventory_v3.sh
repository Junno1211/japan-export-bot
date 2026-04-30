#!/bin/bash
# inventory_v3 cron 用ラッパー
#
# 推奨 crontab（手動登録）:
#   0 */4 * * * /opt/export-bot/scripts/cron_inventory_v3.sh
#
# 既存ロックを尊重し、二重起動を防ぐ
cd /opt/export-bot
LOCK="/tmp/inventory_manager_v3.lock"
if [ -f "$LOCK" ]; then
    AGE=$(($(date +%s) - $(stat -c %Y "$LOCK")))
    if [ $AGE -lt 1800 ]; then
        echo "[$(date '+%F %T')] ロックあり（${AGE}秒経過）→ スキップ"
        exit 0
    fi
fi
timeout 1800 ./venv/bin/python3 -u scripts/inventory_manager_v3.py "$@" >> logs/cron_inventory_v3.log 2>&1
