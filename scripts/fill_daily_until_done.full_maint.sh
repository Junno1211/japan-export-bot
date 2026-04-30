#!/usr/bin/env bash
# fill_daily_until_done.sh の「フルメンテ」版:
#   - 全キュー事前メルカリ走査（purge）あり
#   - mercari_buyable サンプルは全出品シート対象
#
# 使い方:
#   bash scripts/fill_daily_until_done.full_maint.sh
#   bash scripts/fill_daily_until_done.full_maint.sh 60
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export FILL_SKIP_PURGE_UNBUYABLE=0
export FILL_PRIORITY_SAMPLE_ONLY=0
exec bash "${ROOT}/scripts/fill_daily_until_done.sh" "$@"
