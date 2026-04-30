#!/usr/bin/env bash
# 今日(JST)の eBay 出品開始件数が TARGET 件に達するまで test_rules → auto_lister を繰り返す。
# API レート制限(518 等)検出時は CLAUDE.md 準拠で停止。
#
# 使い方:
#   bash scripts/fill_daily_until_done.sh          # デフォルト 70 品
#   bash scripts/fill_daily_until_done.sh 80       # ブースト日など任意件数
#   FILL_TARGET=50 bash scripts/fill_daily_until_done.sh
#
# 結果: logs/fill_daily_RESULT.txt（1行・最終 count）
#       失敗時: logs/fill_daily_ABORT.txt
#
# 優先出品について:
#   auto_lister は常に「優先出品」→「自動出品」の順だが、test_rules が
#   全キュー事前スキャン / 他シートの売切サンプルで落ちると auto_lister まで届かない。
#   既定では FILL_* 環境変数で test_rules を緩め、優先も毎朝の枠に乗りやすくする。
#   フルメンテに戻す:
#     bash scripts/fill_daily_until_done.full_maint.sh
#     または FILL_SKIP_PURGE_UNBUYABLE=0 FILL_PRIORITY_SAMPLE_ONLY=0 bash scripts/fill_daily_until_done.sh ...

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

# 朝の出品ループ用: 他シートのノイズで test_rules が止まらないよう既定で有効（1=有効）
export SKIP_PURGE_UNBUYABLE="${FILL_SKIP_PURGE_UNBUYABLE:-1}"
export PRIORITY_SHEET_SAMPLE_ONLY="${FILL_PRIORITY_SAMPLE_ONLY:-1}"
# auto_lister 内の test_rules subprocess をバイパス（1=スキップ）。親で SKIP_TEST_RULES を渡していればそれを優先
export SKIP_TEST_RULES="${SKIP_TEST_RULES:-${FILL_SKIP_TEST_RULES:-0}}"

# VPS では venv を優先（cron でも同じ Python で揃える）
if [[ -x "${ROOT}/venv/bin/python3" ]]; then
  PY="${ROOT}/venv/bin/python3"
else
  PY="python3"
fi

TARGET="${FILL_TARGET:-${1:-70}}"
case "$TARGET" in
  '' | *[!0-9]*)
    echo "TARGET は正の整数で指定してください（例: 70 または 80）" >&2
    exit 1
    ;;
esac
if [ "$TARGET" -lt 1 ] || [ "$TARGET" -gt 200 ]; then
  echo "TARGET は 1〜200 の範囲で指定してください" >&2
  exit 1
fi

mkdir -p logs
MASTER="$ROOT/logs/fill_daily_loop_${TARGET}_$(date +%Y%m%d_%H%M%S).log"
RESULT="$ROOT/logs/fill_daily_RESULT.txt"
ABORT="$ROOT/logs/fill_daily_ABORT.txt"
rm -f "$RESULT" "$ABORT"

echo "TARGET=$TARGET (JST 当日の GetSellerList StartTime 件数がこれに達するまで実行)" | tee -a "$MASTER"
echo "FILL_SKIP_PURGE_UNBUYABLE=$SKIP_PURGE_UNBUYABLE FILL_PRIORITY_SAMPLE_ONLY=$PRIORITY_SHEET_SAMPLE_ONLY (優先出品を含めやすくする test_rules モード)" | tee -a "$MASTER"

count_today() {
  "${PY}" << 'PY'
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import requests
from config import (
    EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID, EBAY_AUTH_TOKEN,
    EBAY_SITE_ID, EBAY_ENV,
)

JST = timezone(timedelta(hours=9))
now_jst = datetime.now(JST)
start_jst = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)
end_jst = start_jst + timedelta(days=1)
start_utc = start_jst.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
end_utc = end_jst.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
endpoint = {"production": "https://api.ebay.com/ws/api.dll", "sandbox": "https://api.sandbox.ebay.com/ws/api.dll"}.get(EBAY_ENV)
headers = {
    "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
    "X-EBAY-API-CALL-NAME": "GetSellerList",
    "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
    "X-EBAY-API-APP-NAME": EBAY_APP_ID,
    "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
    "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
    "Content-Type": "text/xml",
}
ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
n = 0
page = 1
total_pages = 1
while page <= total_pages:
    body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetSellerListRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <StartTimeFrom>{start_utc}</StartTimeFrom>
  <StartTimeTo>{end_utc}</StartTimeTo>
  <GranularityLevel>Coarse</GranularityLevel>
  <Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>
</GetSellerListRequest>"""
    r = requests.post(endpoint, headers=headers, data=body.encode("utf-8"), timeout=90)
    root = ET.fromstring(r.text)
    ack_el = root.find("ns:Ack", ns)
    if ack_el is None or ack_el.text not in ("Success", "Warning"):
        print(0)
        raise SystemExit(0)
    pr = root.find("ns:PaginationResult", ns)
    if pr is not None:
        tp = pr.find("ns:TotalNumberOfPages", ns)
        if tp is not None and tp.text:
            total_pages = int(tp.text)
    n += len(root.findall(".//ns:ItemArray/ns:Item", ns))
    page += 1
print(n)
PY
}

stagnant=0
prev=-1

while true; do
  n=$(count_today)
  ts=$(date '+%Y-%m-%d %H:%M:%S')
  echo "$ts count=$n target=$TARGET" | tee -a "$MASTER"

  if [ "$n" -ge "$TARGET" ]; then
    echo "$n" | tee "$RESULT"
    "${PY}" "${ROOT}/scripts/notify_fill_daily_slack.py" "$TARGET" "$n" 2>>"${MASTER}" || true
    exit 0
  fi

  if [ "$n" -eq "$prev" ]; then
    stagnant=$((stagnant + 1))
  else
    stagnant=0
  fi
  prev=$n

  if [ "$stagnant" -ge 4 ]; then
    echo "stagnant n=$n target=$TARGET" | tee "$ABORT"
    "${PY}" "${ROOT}/scripts/notify_fill_daily_slack.py" abort "$TARGET" "$n" stagnant 2>>"${MASTER}" || true
    exit 4
  fi

  need=$((TARGET - n))
  echo "$ts need=$need -> auto_lister（中で test_rules が1回だけ走る）" | tee -a "$MASTER"
  # 以前は test_rules をシェルでも実行していたが、auto_lister 内と二重になり
  # メルカリ用ブラウザが無駄に2倍動いていた。シェル側は省略。

  runlog="$ROOT/logs/auto_lister_fill_iter_$(date +%Y%m%d_%H%M%S)_${need}.log"
  "${PY}" auto_lister.py --max-success "$need" >>"$runlog" 2>&1
  rc=$?
  echo "$ts auto_lister exit=$rc" | tee -a "$MASTER"

  if grep -Eiq '(^|[^0-9])518([^0-9]|$)|request limit|rate limit|too many requests' "$runlog" 2>/dev/null; then
    echo "api_limit n=$n target=$TARGET" | tee "$ABORT"
    "${PY}" "${ROOT}/scripts/notify_fill_daily_slack.py" abort "$TARGET" "$n" api_limit 2>>"${MASTER}" || true
    exit 3
  fi

  sleep 8
done
