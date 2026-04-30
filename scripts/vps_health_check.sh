#!/usr/bin/env bash
# VPS の RAM / Swap / ディスク / メモリ多めのプロセスを一覧（ConoHa ダッシュには出ない値）
# 使い方: bash scripts/vps_health_check.sh   （プロジェクト root または /opt/export-bot で）
set -u

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  VPS リソース確認（メモリが足りているかの目安）"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "※ ConoHa のトップ画面だけでは RAM 使用率は分かりません。"
echo "   プラン変更の判断は、下の free と Swap、プロセスを見てください。"
echo ""

if command -v free >/dev/null 2>&1; then
  free -h
  echo ""
  _sw="$(free -b 2>/dev/null | awk '/^Swap:/{print $2+0, $3+0}')"
  swap_total=0
  swap_used=0
  read -r swap_total swap_used <<<"${_sw:-0 0}"
  if [[ "${swap_total:-0}" -gt 0 ]]; then
    pct=$(( swap_used * 100 / swap_total ))
    echo "Swap 使用率: 約 ${pct}% （高いと遅延・OOM の原因になりやすい）"
  fi
else
  echo "(free コマンドなし)"
fi

echo ""
echo "=== ディスク ==="
df -h / 2>/dev/null || df -h . 2>/dev/null || true

echo ""
echo "=== メモリ使用量が多いプロセス（上位）==="
if command -v ps >/dev/null 2>&1; then
  ps aux --sort=-%mem 2>/dev/null | head -15 || ps aux 2>/dev/null | head -15
else
  echo "(ps なし)"
fi

echo ""
echo "=== 目安 ==="
echo "  • 利用可能メモリ（available）が常に極端に少ない → RAM プラン増を検討"
echo "  • Swap がほぼ 100% 張り付き → 負荷低い時間に sudo reboot 後、再度このスクリプト"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
