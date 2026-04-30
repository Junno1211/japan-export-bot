#!/usr/bin/env bash
# Mac で実行。VPS の logs/daily_listing_totals.json を ~/Downloads/ に取る。
# 初回の「Are you sure you want to continue connecting」を出さない（accept-new）。
#
#   cd ~/Downloads/eBay/海外輸出ボット
#   bash scripts/mac_pull_daily_listing_totals.sh
#
# IP を変えるとき:
#   VPS_IP=203.0.113.1 bash scripts/mac_pull_daily_listing_totals.sh
set -euo pipefail
VPS_IP="${VPS_IP:-133.117.76.193}"
VPS_USER="${VPS_USER:-root}"
REMOTE="${VPS_USER}@${VPS_IP}"
DEST="${HOME}/Downloads/daily_listing_totals.json.from-vps"
mkdir -p "$(dirname "$DEST")"
scp -o StrictHostKeyChecking=accept-new \
  "${REMOTE}:/opt/export-bot/logs/daily_listing_totals.json" \
  "$DEST"
echo "保存: $DEST"
