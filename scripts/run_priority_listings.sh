#!/usr/bin/env bash
# 手動キュー（config の PRIORITY_SHEET_NAME、既定「手動」）だけを出品する。
# 使い方:
#   bash scripts/run_priority_listings.sh          # 既定: 溜まっている分をすべて（成功するまでキューを消化）
#   bash scripts/run_priority_listings.sh all      # 同上
#   bash scripts/run_priority_listings.sh 30       # 手動キューで成功30件まで（打ち切りテスト用）
#
# 自動出品系キューが多いと、test_rules 内の purge_unbuyable が全件メルカリ確認し
# 優先出品に到達するまでに非常に時間がかかる。そのため既定で事前スキャンをスキップする。
# フルメンテをかけたい場合: SKIP_PURGE_UNBUYABLE=0 bash scripts/run_priority_listings.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
N="${1:-all}"
export SKIP_PURGE_UNBUYABLE="${SKIP_PURGE_UNBUYABLE:-1}"
export PRIORITY_SHEET_SAMPLE_ONLY="${PRIORITY_SHEET_SAMPLE_ONLY:-1}"
mkdir -p logs
LOG="$ROOT/logs/priority_listings_${N}_$(date +%Y%m%d_%H%M%S).log"
# $LOG の直後に全角「（」を続けると set -u 環境で ${LOG?...} と誤解釈されることがあるため printf で分離する
printf '📝 ログ: %s\n' "${LOG}"
echo '（下に進捗も表示します。止まって見えても数分〜かかります）'
{
  echo "=== $(date) priority mode=$N SKIP_PURGE_UNBUYABLE=$SKIP_PURGE_UNBUYABLE PRIORITY_SHEET_SAMPLE_ONLY=$PRIORITY_SHEET_SAMPLE_ONLY ==="
  # test_rules は auto_lister 起動時に1回だけ実行される（ここで二度走らせない＝メモリ・時間の節約）
  if [[ "$N" == "all" ]]; then
    # --max-priority-success / --max-success なし = 手動キューを空に近づけるまで。自動出品系は max-auto-success 0 で触らない。
    exec python3 auto_lister.py --max-auto-success 0
  else
    exec python3 auto_lister.py \
      --max-priority-success "$N" \
      --max-auto-success 0 \
      --max-success "$N"
  fi
} 2>&1 | tee -a "${LOG}"
