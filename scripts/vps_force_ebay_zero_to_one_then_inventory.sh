#!/usr/bin/bash
# VPS /opt/export-bot のみ。
# Active かつ在庫0をメルカリ確認なしで eBay quantity=1 → 続けて inventory_manager。
# SSH が切れても VPS 上で最後まで走らせるなら nohup 例は COPY_PASTE_SETUP.txt N 節。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "$ROOT" != "/opt/export-bot" ]]; then
  echo "【エラー】VPS の /opt/export-bot で実行してください。" >&2
  exit 1
fi
cd "$ROOT"
PY="${ROOT}/venv/bin/python3"
if [[ ! -x "$PY" ]]; then
  echo "venv が無い: $PY" >&2
  exit 1
fi
LOGDIR="${ROOT}/logs"
mkdir -p "$LOGDIR"
TS="$(date +%Y%m%d_%H%M%S)"
LOG="$LOGDIR/force_qty1_then_inv_${TS}.log"
{
  echo "=== 1/2 force_ebay_active_zero_to_qty1（メルカリ未確認）==="
  "$PY" -u scripts/force_ebay_active_zero_to_qty1.py
  echo "=== 2/2 inventory_manager ==="
  "$PY" -u inventory_manager.py
  echo "=== 完了 ==="
} 2>&1 | tee -a "$LOG"
echo "ログ: $LOG"
