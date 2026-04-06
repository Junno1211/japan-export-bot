#!/usr/bin/env bash
# ConoHa VPS cron: 03:00 JST — 対象4部署の auto_sourcer → auto_lister（最大60件成功）
# 各部署でエラーが出ても次へ進む（set -e なし）

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

PYTHON="${PYTHON:-/usr/bin/python3}"
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/cron_daily_$(date +%Y%m%d).log"
exec >>"$LOG_FILE" 2>&1

echo "===== START $(date '+%Y-%m-%d %H:%M:%S %z') pid=$$ ====="
echo "PROJECT_ROOT=$PROJECT_ROOT"
echo "PYTHON=$PYTHON ($("$PYTHON" --version 2>&1))"

DEPTS=(dragonball bbm_baseball bbm_mlb_japan bikkuriman)

for dept in "${DEPTS[@]}"; do
  echo "---- auto_sourcer --dept $dept $(date '+%Y-%m-%d %H:%M:%S') ----"
  if "$PYTHON" auto_sourcer.py --dept "$dept"; then
    echo "OK auto_sourcer --dept $dept"
  else
    ec=$?
    echo "WARN auto_sourcer --dept $dept exit=$ec (continuing)"
  fi
done

echo "---- auto_lister --max-success 60 $(date '+%Y-%m-%d %H:%M:%S') ----"
if "$PYTHON" auto_lister.py --max-success 60; then
  echo "OK auto_lister"
else
  ec=$?
  echo "WARN auto_lister exit=$ec"
fi

echo "===== END $(date '+%Y-%m-%d %H:%M:%S %z') ====="
