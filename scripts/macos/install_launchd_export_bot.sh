#!/usr/bin/env bash
# 在庫・注文を launchd（ユーザー領域）で毎時実行する。cron の代替用。
# Mac がスリープ中は cron と同様に定時ジョブは原則動かない。24時間は VPS かスリープしない Mac が必要。
# 【重要】在庫・注文は cron と二重登録しないこと。どちらか一方だけ使う。
#
# 使い方:
#   bash scripts/macos/install_launchd_export_bot.sh
#   bash scripts/macos/install_launchd_export_bot.sh --dry-run
#
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
AGENT_DIR="${HOME}/Library/LaunchAgents"
PY="${PYTHON3_FOR_BOT:-/usr/bin/python3}"
DRY=false
[[ "${1:-}" == "--dry-run" ]] && DRY=true

mkdir -p "$ROOT/logs"
mkdir -p "$AGENT_DIR"

inv_plist="$AGENT_DIR/com.japanexport.inventory.plist"
ord_plist="$AGENT_DIR/com.japanexport.order_monitor.plist"

emit_plist() {
  local label=$1
  local minute=$2
  local script=$3
  local log_out=$4
  local log_err=$5
  cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$label</string>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>-u</string>
    <string>$script</string>
  </array>
  <key>StandardOutPath</key>
  <string>$log_out</string>
  <key>StandardErrorPath</key>
  <string>$log_err</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Minute</key>
    <integer>$minute</integer>
  </dict>
</dict>
</plist>
PLIST
}

echo "ROOT=$ROOT"
echo "Python: $PY"
echo ""

if $DRY; then
  echo "=== DRY: 在庫（毎時0分）plist ==="
  emit_plist "com.japanexport.inventory" 0 inventory_manager.py \
    "$ROOT/logs/inventory.launchd.log" "$ROOT/logs/inventory.launchd.err.log"
  echo ""
  echo "=== DRY: 注文（毎時5分）plist ==="
  emit_plist "com.japanexport.order_monitor" 5 order_monitor.py \
    "$ROOT/logs/orders.launchd.log" "$ROOT/logs/orders.launchd.err.log"
  exit 0
fi

emit_plist "com.japanexport.inventory" 0 inventory_manager.py \
  "$ROOT/logs/inventory.launchd.log" "$ROOT/logs/inventory.launchd.err.log" >"$inv_plist"
emit_plist "com.japanexport.order_monitor" 5 order_monitor.py \
  "$ROOT/logs/orders.launchd.log" "$ROOT/logs/orders.launchd.err.log" >"$ord_plist"

chmod 644 "$inv_plist" "$ord_plist"

launchctl bootout "gui/$(id -u)" "$inv_plist" 2>/dev/null || true
launchctl bootout "gui/$(id -u)" "$ord_plist" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$inv_plist"
launchctl bootstrap "gui/$(id -u)" "$ord_plist"

echo "✅ 登録: $inv_plist"
echo "✅ 登録: $ord_plist"
echo ""
echo "⚠️  cron に同じ在庫・注文行があると二重実行です。crontab -e で該当行をコメントアウトしてください。"
