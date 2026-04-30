#!/usr/bin/env bash
# VPS で1回: systemd に手動キュー用ユニットを登録する
#   sudo bash /opt/export-bot/scripts/install_priority_systemd.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/deploy/systemd/export-bot-priority@.service"
DST="/etc/systemd/system/export-bot-priority@.service"

if [[ ! -f "$SRC" ]]; then
  echo "見つかりません: $SRC" >&2
  exit 1
fi
if [[ "$(id -u)" != "0" ]]; then
  echo "root で実行してください: sudo bash $0" >&2
  exit 1
fi

cp -a "$SRC" "$DST"
systemctl daemon-reload

echo "✅ 登録: $DST"
echo ""
echo "手動キューを溜まり分すべて（バックグラウンド相当・journal も参照可）:"
echo "  sudo systemctl start export-bot-priority@all"
echo "  sudo journalctl -u export-bot-priority@all -f"
echo ""
echo "件数で打ち切る例（最大10件成功まで）:"
echo "  sudo systemctl start export-bot-priority@10"
echo ""
echo "※ 同時実行は auto_lister のロックで1本に制限されます。"
