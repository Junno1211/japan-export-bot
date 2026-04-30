#!/usr/bin/env bash
# メルカリAPIで「販売中」と取れた SKU だけ、eBay 数量を 1 に戻す。それ以外は変更しない。
# 必ず VPS（/opt/export-bot）で実行。Mac では動かない。
set -euo pipefail
ROOT="${ROOT:-/opt/export-bot}"
cd "$ROOT"
mkdir -p logs
STAMP="$(date +%Y%m%d_%H%M%S)"
exec ./venv/bin/python3 ebay_restock_all.py --ignore-sold-csv 2>&1 | tee "logs/emergency_restock_${STAMP}.log"
