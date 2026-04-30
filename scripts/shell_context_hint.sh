#!/usr/bin/env bash
# Mac / VPS / ローカル Linux の取り違え・二重 SSH・Swap を表示（迷ったらこれ）
# VPS: bash /opt/export-bot/scripts/shell_context_hint.sh
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
BOT="/opt/export-bot"
OS="$(uname -s || true)"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  海外輸出ボット — 今どこで作業しているか"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ "$OS" == "Darwin" ]]; then
  echo ""
  echo "● macOS です（開発用 Mac）。"
  echo "  → プロジェクト例:  cd ~/Downloads/eBay/海外輸出ボット"
  echo ""
  echo "  ● 一度だけ:  bash scripts/disable_mac_cron_auto_lister.sh"
  echo "  ● VPS へ:    ssh root@（VPSのIP）"
  echo "  ● 更新反映:  bash deploy.sh → VPS で pip install -r requirements.txt"
  echo ""

elif [[ "$OS" == "Linux" ]] && [[ -d "$BOT" ]] && [[ -f "$BOT/auto_lister.py" ]]; then
  echo ""
  echo "● 本番 VPS（${BOT}）とみなせます。"
  echo "  → cd $BOT"
  echo ""
  echo "  × 使わない:  cd ~/Downloads/...  （Mac のパス。VPS には無い）"
  echo "  × 不要:      同じサーバへ再度 ssh しない（もうログイン済みなら cd のみ）"
  echo ""
  echo "  × 動かさない: disable_mac_cron_auto_lister.sh（Mac 専用）"
  echo ""
  if command -v free >/dev/null 2>&1; then
    echo "● メモリ / Swap"
    free -h 2>/dev/null || true
    _sw="$(free -b 2>/dev/null | awk '/^Swap:/{print $2+0, $3+0}')"
    swap_total=0
    swap_used=0
    read -r swap_total swap_used <<<"${_sw:-0 0}"
    if [[ "${swap_total:-0}" -gt 0 ]]; then
      pct=$(( swap_used * 100 / swap_total ))
      if [[ "$pct" -ge 75 ]]; then
        echo ""
        echo "  ⚠️ Swap 使用が約 ${pct}% です。遅延・不安定の原因になり得ます。"
        echo "     落ち着いたら: sudo reboot"
      fi
    fi
    echo ""
  fi
  echo "● コード更新直後:  cd $BOT && ./venv/bin/pip install -r requirements.txt"
  echo ""

elif [[ "$OS" == "Linux" ]]; then
  echo ""
  echo "● Linux ですが ${BOT}（本番パス）ではありません。"
  if [[ -f "$ROOT/auto_lister.py" ]]; then
    echo "  → いまのリポジトリ: $ROOT"
    echo "  本番へは Mac から deploy.sh で VPS に送り、VPS 上で pip を実行してください。"
  else
    echo "  プロジェクト直下が不明です。海外輸出ボットのフォルダで実行しているか確認してください。"
  fi
  echo ""

else
  echo ""
  echo "● OS: $OS — 手順は Mac に近いです（ターミナルでプロジェクトへ cd → deploy は Mac から）。"
  echo ""
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
