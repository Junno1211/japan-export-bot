#!/usr/bin/env bash
set -u
AGENT_DIR="${HOME}/Library/LaunchAgents"
inv_plist="$AGENT_DIR/com.japanexport.inventory.plist"
ord_plist="$AGENT_DIR/com.japanexport.order_monitor.plist"
UID_NUM="$(id -u)"
for p in "$inv_plist" "$ord_plist"; do
  [[ -f "$p" ]] || continue
  launchctl bootout "gui/$UID_NUM" "$p" 2>/dev/null || true
  rm -f "$p"
  echo "removed $p"
done
echo "アンインストール完了。cron を再度有効にする場合は crontab を戻してください。"
