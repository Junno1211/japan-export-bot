#!/usr/bin/env bash
# root の crontab で fill_daily を 70 に揃え、壊れた行・重複 0 4 行を除去する。
# 使い方（VPS・root）:
#   cd /opt/export-bot && bash scripts/fix_crontab_fill_daily_70.sh
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
BK="logs/crontab_backup_$(date +%Y%m%d_%H%M%S).txt"
crontab -l >"$BK"
echo "バックアップ: $ROOT/$BK"
crontab -l 2>/dev/null | /usr/bin/python3 "$ROOT/scripts/fix_crontab_fill_daily_70.py" | crontab -
echo "crontab を更新しました。確認:"
crontab -l | grep -E 'fill_daily|Fill' || crontab -l | grep fill_daily_until_done || true
echo "---"
crontab -l | grep -n '0 4 \* \* \*' || true
