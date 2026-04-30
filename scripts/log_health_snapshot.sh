#!/usr/bin/env bash
# 在庫・注文ログの末尾と、明らかな異常行をざっと表示
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

echo "=== logs/inventory.log (末尾30行) ==="
if [[ -f logs/inventory.log ]]; then
  tail -30 logs/inventory.log
else
  echo "(なし)"
fi
echo ""
echo "=== logs/orders.log (末尾30行) ==="
if [[ -f logs/orders.log ]]; then
  tail -30 logs/orders.log
else
  echo "(なし)"
fi
echo ""
echo "=== 警告っぽい行（inventory.log 今日分・最大40行）==="
if [[ -f logs/inventory.log ]]; then
  grep -E "ERROR|Traceback|例外|失敗|⚠️|❌|別の在庫チェックが実行中" logs/inventory.log 2>/dev/null | tail -40 || true
else
  echo "(なし)"
fi
echo ""
echo "=== 警告っぽい行（orders.log 今日分・最大20行）==="
if [[ -f logs/orders.log ]]; then
  grep -E "ERROR|Traceback|失敗|Error|API Error" logs/orders.log 2>/dev/null | tail -20 || true
else
  echo "(なし)"
fi
