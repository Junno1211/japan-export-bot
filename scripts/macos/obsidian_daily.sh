#!/usr/bin/env bash
# 日報 Markdown を再生成し、任意で Obsidian で開く。
#
# 使い方:
#   bash scripts/macos/obsidian_daily.sh
#   bash scripts/macos/obsidian_daily.sh --open
#   bash scripts/macos/obsidian_daily.sh --open --open-dashboard
#
# 環境変数:
#   PYTHON3_FOR_BOT  既定: python3
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PY="${PYTHON3_FOR_BOT:-python3}"
exec "$PY" generate_daily_listing_report.py "$@"
