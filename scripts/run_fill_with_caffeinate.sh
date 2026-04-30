#!/usr/bin/env bash
# 長時間の出品ループ中に Mac がスリープしにくくする（caffeinate）。
# 例: bash scripts/run_fill_with_caffeinate.sh
#     bash scripts/run_fill_with_caffeinate.sh 60   → fill_daily_until_done.sh に 60 を渡す
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
exec /usr/bin/caffeinate -dims /bin/bash "$ROOT/scripts/fill_daily_until_done.sh" "$@"
