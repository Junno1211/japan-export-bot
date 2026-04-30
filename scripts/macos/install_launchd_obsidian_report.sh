#!/usr/bin/env bash
# 毎日定時に generate_daily_listing_report.py を実行（Obsidian は起動しない）。
# Mac のローカル時計の「その時刻」で動く（日本なら通常 JST）。
#
# 使い方:
#   bash scripts/macos/install_launchd_obsidian_report.sh
#   bash scripts/macos/install_launchd_obsidian_report.sh --hour 22 --minute 0
#   bash scripts/macos/install_launchd_obsidian_report.sh --uninstall
#
# 既定: 毎日 22:00
#
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
AGENT_DIR="${HOME}/Library/LaunchAgents"
PY="${PYTHON3_FOR_BOT:-/usr/bin/python3}"
LABEL="com.japanexport.obsidian_daily_report"
PLIST="$AGENT_DIR/${LABEL}.plist"

HOUR=22
MINUTE=0

usage() {
  echo "Usage: $0 [--hour H] [--minute M] | --uninstall"
  echo "  Default: daily at 22:00 local time"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --uninstall)
      launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
      rm -f "$PLIST"
      echo "Removed $PLIST"
      exit 0
      ;;
    --hour)
      HOUR="${2:?}"
      shift 2
      ;;
    --minute)
      MINUTE="${2:?}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "$HOUR" -lt 0 || "$HOUR" -gt 23 ]] || [[ "$MINUTE" -lt 0 || "$MINUTE" -gt 59 ]]; then
  echo "hour must be 0-23, minute must be 0-59" >&2
  exit 1
fi

mkdir -p "$ROOT/logs" "$AGENT_DIR"

cat >"$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>-u</string>
    <string>$ROOT/generate_daily_listing_report.py</string>
  </array>
  <key>StandardOutPath</key>
  <string>$ROOT/logs/obsidian_report.launchd.log</string>
  <key>StandardErrorPath</key>
  <string>$ROOT/logs/obsidian_report.launchd.err.log</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>$HOUR</integer>
    <key>Minute</key>
    <integer>$MINUTE</integer>
  </dict>
</dict>
</plist>
PLIST

chmod 644 "$PLIST"
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

printf "Installed %s (daily %02d:%02d local time, no GUI)\n" "$PLIST" "$HOUR" "$MINUTE"
echo "ログ: $ROOT/logs/obsidian_report.launchd.log"
