#!/usr/bin/env bash
# 在庫まわりの状態をまとめて表示。VPS は鍵が通れば crontab も見る。
# 使い方: --fix-crontab を付けると scripts/fix_crontab_tilde_paths.py を実行（~→絶対パス・python3 正規化）
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# 任意: scripts/vps.env で VPS 接続先を上書き（例は vps.env.example）
if [[ -f "$ROOT/scripts/vps.env" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/scripts/vps.env"
fi
: "${VPS_HOST:=133.117.76.193}"
: "${VPS_USER:=root}"
: "${VPS_SSH_PORT:=22}"
: "${VPS_SSH_KEY:=$HOME/.ssh/mercari_vps}"
: "${VPS_BOT_ROOT:=/opt/mercari_monitor}"

if [ "${1:-}" = "--fix-crontab" ]; then
  echo "=== crontab 正規化 ==="
  python3 "$ROOT/scripts/fix_crontab_tilde_paths.py" || true
  echo ""
fi
echo "=== Mac: crontab (inventory / order 関連) ==="
crontab -l 2>/dev/null | grep -E "inventory|order_monitor|fill_daily|fill60|japan-export|launchd|133\.117" || true
echo ""
echo "=== Mac: launchd（在庫・注文）==="
launchctl list 2>/dev/null | grep -E "japanexport\.(inventory|order_monitor)" || echo "(未登録または一覧に出ません)"
echo ""
echo "=== Mac: inventory.log (末尾15行) ==="
if [ -f "$ROOT/logs/inventory.log" ]; then
  ls -la "$ROOT/logs/inventory.log"
  tail -15 "$ROOT/logs/inventory.log"
else
  echo "(なし)"
fi
echo ""
echo "=== VPS: SSH プローブ (BatchMode) host=$VPS_USER@$VPS_HOST port=$VPS_SSH_PORT ==="
SSH_BASE=(ssh -i "$VPS_SSH_KEY" -p "$VPS_SSH_PORT" -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=12)
REMOTE_CHECK=$(cat <<'EOS'
echo OK
crontab -l 2>/dev/null | grep -E "inventory_manager|order_monitor|mercari_monitor|japan-export" || true
for d in /root/japan-export-bot /opt/bot /opt/mercari_monitor; do
  if [ -f "$d/inventory_manager.py" ]; then echo "inventory_manager.py:$d"; fi
done
EOS
)
"${SSH_BASE[@]}" "${VPS_USER}@${VPS_HOST}" "$REMOTE_CHECK" 2>&1
_ssh_ec=$?
if [ "$_ssh_ec" -eq 0 ]; then
  echo ""
  echo "(VPS 接続成功。BOT_ROOT 目安: $VPS_BOT_ROOT — 実際のパスは上記 inventory_manager.py:... を優先)"
else
  echo ""
  echo "(VPS に入れませんでした exit=${_ssh_ec}。鍵・パスワード・FW・IP変更・sshd停止を確認)"
  echo "  → VPS_GUIDE.md「SSH Connection refused のとき」"
  echo "  → VPS 復旧後: scripts/vps_cron_snippet.txt を BOT_ROOT に合わせて crontab へ"
fi
echo ""
echo "ヒント: crontab の ~ / python3 → bash $0 --fix-crontab"
echo "ヒント: 行が壊れた → python3 \"$ROOT/scripts/repair_crontab_project_jobs.py\""
echo "ヒント: crontab 書込が止まる → python3 \"$ROOT/scripts/repair_crontab_project_jobs.py\" --write-file=logs/crontab.new.txt && crontab \"$ROOT/logs/crontab.new.txt\""
echo "ヒント: cron の代わりに launchd → bash \"$ROOT/scripts/macos/install_launchd_export_bot.sh\"（スリープ対策にはならない。24h は VPS 等）"
echo "ヒント: ログ健全性 → bash \"$ROOT/scripts/log_health_snapshot.sh\""
echo "ヒント: VPS 接続先を変える → cp \"$ROOT/scripts/vps.env.example\" \"$ROOT/scripts/vps.env\""
