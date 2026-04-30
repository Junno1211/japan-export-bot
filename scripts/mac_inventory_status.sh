#!/usr/bin/env bash
# Mac のターミナル専用: VPS の在庫 cron・.env フラグ・直近ログ（監視用1行）をまとめて表示。
#
#   cd ~/Downloads/eBay/海外輸出ボット && bash scripts/mac_inventory_status.sh
#
# VPS_IP / VPS_USER で接続先を上書き可。
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "このスクリプトは Mac（ターミナル）専用です。" >&2
  exit 1
fi

VPS_IP="${VPS_IP:-133.117.76.193}"
VPS_USER="${VPS_USER:-root}"
REMOTE="${VPS_USER}@${VPS_IP}"

ssh -o ServerAliveInterval=60 -o StrictHostKeyChecking=accept-new "$REMOTE" 'bash -s' <<'REMOTE'
set -e
BOT="${BOT:-/opt/export-bot}"
cd "$BOT" 2>/dev/null || { echo "cd $BOT 失敗"; exit 1; }
echo "=== cron（inventory_manager）==="
crontab -l 2>/dev/null | grep -E "inventory_manager" || echo "(該当行なし)"
echo ""
echo "=== .env（INVENTORY_APPLY_EBAY_OOS / MAX_OUT_OF_STOCK_PER_RUN）==="
if [[ -f .env ]]; then
  grep -E "^INVENTORY_APPLY_EBAY_OOS" .env || echo "(INVENTORY_APPLY_EBAY_OOS 未定義 → config 既定でオン)"
  grep -E "^MAX_OUT_OF_STOCK_PER_RUN" .env || echo "(MAX_OUT_OF_STOCK_PER_RUN 未定義 → config 既定 0＝無制限)"
  grep -E "^INVENTORY_ANOMALY_MIN_START_ACTIVE" .env || echo "(INVENTORY_ANOMALY_MIN_START_ACTIVE 未定義 → config 既定 30)"
  grep -E "^INVENTORY_ANOMALY_MAX_END_ACTIVE" .env || echo "(INVENTORY_ANOMALY_MAX_END_ACTIVE 未定義 → config 既定 0＝終了時0件で異常Slack)"
else
  echo "(.env なし → 両方 config 既定: 適用オン・OOS件数上限なし)"
fi
echo ""
echo "=== 直近 cron_inventory.log（INVENTORY_PIPELINE / 在庫チェック）==="
if [[ -f logs/cron_inventory.log ]]; then
  tail -n 60 logs/cron_inventory.log | grep -E "INVENTORY_PIPELINE_RESULT|在庫チェック開始|Playwright 購入CTA" || tail -n 15 logs/cron_inventory.log
else
  echo "(logs/cron_inventory.log なし)"
fi
REMOTE
