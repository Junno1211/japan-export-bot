#!/bin/bash
# ============================================================
#  📋設定を送る.command
#  設定ファイル＋修正済みコードをVPSに送信します
#  ★ ファイルを変更した後に実行してください ★
# ============================================================

cd "$(dirname "$0")"

VPS_IP="133.117.76.193"
VPS_USER="root"
VPS_DIR="/opt/mercari_monitor"
KEY_FILE="$HOME/.ssh/mercari_vps"
VPS_PASS="***REMOVED***"

echo "========================================"
echo "  設定ファイルをVPSに送信"
echo "========================================"
echo ""

# SSH鍵があれば鍵認証、なければパスワード認証
if [ -f "$KEY_FILE" ]; then
  SCP_OPTS="-i $KEY_FILE -o StrictHostKeyChecking=no"
  SSH_OPTS="-i $KEY_FILE -o StrictHostKeyChecking=no -o ConnectTimeout=15 -o PasswordAuthentication=no"
  echo "🔑 SSH鍵認証で接続します"
else
  SCP_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=30"
  SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=30 -o ServerAliveInterval=10"
  echo "🔐 パスワード認証: ***REMOVED***"
fi

ssh-keygen -R ${VPS_IP} 2>/dev/null
echo ""

echo "📤 ファイルを転送中..."
scp $SCP_OPTS \
  config.py \
  google_credentials.json \
  sheets_manager.py \
  main.py \
  mercari_checker.py \
  ${VPS_USER}@${VPS_IP}:${VPS_DIR}/

if [ $? -ne 0 ]; then
  echo "❌ 転送失敗。🔑SSH鍵設定.command を先に実行してください"
  read -p "Enterキーを押して終了..."
  exit 1
fi

echo ""
echo "✅ 転送完了！"
echo ""
echo "🧪 Google Sheets接続テスト中..."
ssh $SSH_OPTS ${VPS_USER}@${VPS_IP} \
  "cd ${VPS_DIR} && source venv/bin/activate && timeout 30 python3 -c \"
from sheets_manager import read_active_items
items = read_active_items()
print(f'✅ Google Sheets接続成功！ {len(items)}件のアイテムを読み込みました')
for i in items[:3]:
    print(f'  - {i[\"mercari_url\"][:50]}')
\" 2>&1" 2>&1

echo ""
read -p "Enterキーを押して終了..."
