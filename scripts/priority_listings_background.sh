#!/usr/bin/env bash
# ============================================================
# priority_listings_background.sh — 手動キューを PC なしで回す（VPS 専用）
#
# SSH を切っても処理は継続（nohup）。
# 同時に2本走らせない（flock）。
#
# 使い方:
#   cd /opt/export-bot && bash scripts/priority_listings_background.sh       # 溜まっている分すべて
#   cd /opt/export-bot && bash scripts/priority_listings_background.sh 30   # 成功30件で打ち切り
#
# ログ:
#   logs/bg_priority_listings_<N>_<日時>.log
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
N="${1:-all}"
mkdir -p "$ROOT/logs" "$ROOT/run"

STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="$ROOT/logs/bg_priority_listings_${N}_${STAMP}.log"
LOCK_FILE="/tmp/export-bot-priority-launch.lock"

export ROOT N LOCK_FILE
nohup env ROOT="$ROOT" N="$N" LOCK_FILE="$LOCK_FILE" bash -c '
(
  flock -n 200 || { echo "手動出品は既に別プロセスで実行中です。"; exit 1; }
  cd "$ROOT"
  exec bash scripts/run_priority_listings.sh "$N"
) 200>"$LOCK_FILE"
' >>"$LOG" 2>&1 &

PID=$!
echo "$PID" >"$ROOT/run/priority_listings_bg.pid"
echo "✅ バックグラウンド起動 PID=$PID"
echo "📝 ログ: $LOG"
echo ""
echo "進捗: tail -f $LOG"
echo "（SSH を閉じても VPS 上では動き続けます）"
