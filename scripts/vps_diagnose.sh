#!/usr/bin/env bash
# VPS 疎通とチェックリスト（サーバ復旧はパネル側が必要）
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$ROOT/scripts/vps.env" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/scripts/vps.env"
fi
: "${VPS_HOST:=133.117.76.193}"
: "${VPS_USER:=root}"
: "${VPS_SSH_PORT:=22}"
: "${VPS_SSH_KEY:=$HOME/.ssh/mercari_vps}"

echo "=== VPS 診断 ==="
echo "HOST=$VPS_USER@$VPS_HOST port=$VPS_SSH_PORT key=$VPS_SSH_KEY"
echo ""
echo "チェックリスト（Connection refused のとき）:"
echo "  1. コンソールで VM 電源・ステータス"
echo "  2. セキュリティグループ / FW で TCP22"
echo "  3. 契約画面のグローバル IP が変わっていないか → scripts/vps.env"
echo "  4. sshd が別ポートなら VPS_SSH_PORT を設定"
echo ""
if [[ ! -f "$VPS_SSH_KEY" ]]; then
  echo "鍵ファイルなし: $VPS_SSH_KEY"
  exit 1
fi
echo "=== SSH (BatchMode, ${VPS_SSH_PORT}) ==="
if ssh -i "$VPS_SSH_KEY" -p "$VPS_SSH_PORT" -o BatchMode=yes -o ConnectTimeout=10 \
    -o StrictHostKeyChecking=no "${VPS_USER}@${VPS_HOST}" 'echo OK; hostname; crontab -l 2>/dev/null | head -20'; then
  echo ""
  echo "接続成功。cron 整備は scripts/vps_cron_snippet.txt を参照。"
else
  echo ""
  echo "接続失敗。上記チェックリストと VPS_GUIDE.md を参照。"
  exit 2
fi
