#!/usr/bin/env bash
# 【臨時用】本番の手動キューは VPS のみ: ssh → cd /opt/export-bot →
#   bash scripts/priority_listings_background.sh
# Mac と VPS で同時に回すと二重出品の原因になる。
#
# 「手動」タブだけを eBay に出品（自動出品タブは触らない）。
#
# 使い方:
#   bash manual_listing.sh           # 手動キューを消化するまで（自動出品は max 0）
#   bash manual_listing.sh all       # 同上
#   bash manual_listing.sh 5         # 手動で成功が5件に達したら打ち切り
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec bash "$ROOT/scripts/run_priority_listings.sh" "$@"
