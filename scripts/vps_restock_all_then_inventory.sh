#!/usr/bin/bash
# VPS 上の /opt/export-bot でのみ実行すること（Mac のリポジトリでは動かない）。
# メルカリAPIが販売中の在庫0だけ eBay を1に戻す → 続けて在庫管理1周。
# 誤 SOLD 記録があるときは第1引数に ignore を付ける。
#
#   ssh root@<VPS> 'cd /opt/export-bot && bash scripts/vps_restock_all_then_inventory.sh ignore'
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "$ROOT" != "/opt/export-bot" ]]; then
  echo "【エラー】このスクリプトは VPS の /opt/export-bot でだけ実行してください。" >&2
  echo "  いまのディレクトリ解決結果: $ROOT" >&2
  echo "  Mac で cd /opt/export-bot は使えません（そのパスは VPS 専用）。" >&2
  echo "" >&2
  echo "【Mac から 1 行（誤 SOLD 対策で ignore）】" >&2
  echo "ssh -o ServerAliveInterval=60 -o StrictHostKeyChecking=accept-new root@133.117.76.193 'cd /opt/export-bot && bash scripts/vps_restock_all_then_inventory.sh ignore'" >&2
  echo "" >&2
  echo "【Mac から 1 行（items.csv の SOLD を尊重）】" >&2
  echo "ssh -o ServerAliveInterval=60 -o StrictHostKeyChecking=accept-new root@133.117.76.193 'cd /opt/export-bot && bash scripts/vps_restock_all_then_inventory.sh'" >&2
  exit 1
fi
cd "$ROOT"
PY="${ROOT}/venv/bin/python3"
if [[ ! -x "$PY" ]]; then
  echo "【エラー】venv が無い: $PY （vps_setup.sh 未実行の可能性）" >&2
  exit 1
fi
IGN=()
if [[ "${1:-}" == "ignore" ]]; then
  IGN=(--ignore-sold-csv)
fi
LOGDIR="${ROOT}/logs"
mkdir -p "$LOGDIR"
TS="$(date +%Y%m%d_%H%M%S)"
echo "=== 1/2 ebay_restock_all ${IGN[*]:-} ===" | tee -a "$LOGDIR/restock_then_inv_${TS}.log"
"$PY" -u ebay_restock_all.py "${IGN[@]}" 2>&1 | tee -a "$LOGDIR/restock_then_inv_${TS}.log"
echo "=== 2/2 inventory_manager ===" | tee -a "$LOGDIR/restock_then_inv_${TS}.log"
"$PY" -u inventory_manager.py 2>&1 | tee -a "$LOGDIR/restock_then_inv_${TS}.log"
echo "=== 完了。在庫 cron を 3 時間にする例（未設定なら）: ===" | tee -a "$LOGDIR/restock_then_inv_${TS}.log"
echo "crontab -l | sed '/inventory_manager\.py/ s/^0 \\* \\* \\* \\*/0 *\\/3 * * */' | crontab -" | tee -a "$LOGDIR/restock_then_inv_${TS}.log"
echo "crontab -l | grep inventory_manager" | tee -a "$LOGDIR/restock_then_inv_${TS}.log"
