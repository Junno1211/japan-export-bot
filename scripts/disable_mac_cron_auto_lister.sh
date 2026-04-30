#!/usr/bin/env bash
# Mac の crontab から auto_lister.py を含む行を削除する（VPS に処理を寄せるとき用）
# 使い方: bash scripts/disable_mac_cron_auto_lister.sh
# ※ macOS 専用。VPS（Linux）では実行しない。
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "このスクリプトは Mac（macOS）専用です。VPS では不要です。終了します。" >&2
  exit 0
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/logs"
BACKUP="$ROOT/logs/crontab_backup_$(date +%Y%m%d_%H%M%S).txt"

ORIG="$(mktemp)"
NEW="$(mktemp)"
if ! crontab -l >"$ORIG" 2>/dev/null; then
  echo "crontab が空です。何もしません。"
  rm -f "$ORIG" "$NEW"
  exit 0
fi

grep -v "auto_lister\.py" "$ORIG" >"$NEW" || true

if cmp -s "$ORIG" "$NEW"; then
  echo "変更なし（auto_lister.py を含む行はありませんでした）"
  rm -f "$ORIG" "$NEW"
  exit 0
fi

cp "$ORIG" "$BACKUP"
crontab "$NEW"
rm -f "$ORIG" "$NEW"
echo "✅ crontab から auto_lister.py 行を削除しました。"
echo "   バックアップ: $BACKUP"
echo "   確認: crontab -l"
