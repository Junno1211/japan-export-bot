#!/usr/bin/env bash
# ============================================================
# ensure_priority_cron.sh — 手動キュー（priority_listings）を 30 分ごとに回す cron を入れる
#
# ・何度実行しても同じ結果（既存の priority_listings 行は置き換え）
# ・logs/ を作成し、cron_priority_bg.log に stdout/stderr が溜まる
#
# 使い方（VPS）:
#   cd /opt/export-bot && bash scripts/ensure_priority_cron.sh
#
# Mac から（パスワードまたは鍵）:
#   ssh -o ServerAliveInterval=60 root@133.117.76.193 'cd /opt/export-bot && bash scripts/ensure_priority_cron.sh'
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/logs"

LINE="*/30 * * * * cd $ROOT && bash scripts/priority_listings_background.sh >> logs/cron_priority_bg.log 2>&1"

( crontab -l 2>/dev/null | grep -v 'priority_listings_background\.sh' || true
  echo "$LINE"
) | crontab -

echo "OK — 手動キュー用 cron を登録しました（30 分ごと）。"
echo "--- crontab（該当行）---"
crontab -l 2>/dev/null | grep -n 'priority_listings_background' || { echo "(grep に出ませんでした)"; crontab -l; }
