#!/usr/bin/env bash
# 互換用: 60 品ブースト日はこのスクリプトを使う（内部は fill_daily_until_done.sh 60）。
exec "$(cd "$(dirname "$0")" && pwd)/fill_daily_until_done.sh" 60
