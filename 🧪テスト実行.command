#!/bin/bash
# ============================================================
#  🧪テスト実行.command
#  VPSの動作確認・ログ確認・手動テスト実行
#  ★ 先に 🔑SSH鍵設定.command を実行してください ★
# ============================================================

cd "$(dirname "$0")"

VPS_IP="133.117.76.193"
VPS_USER="root"
VPS_DIR="/opt/mercari_monitor"
KEY_FILE="$HOME/.ssh/mercari_vps"

# SSH接続オプション
SSH_OPTS="-i $KEY_FILE -o StrictHostKeyChecking=no -o ConnectTimeout=15 -o PasswordAuthentication=no"

echo "========================================"
echo "  メルカリ監視システム - 動作確認"
echo "========================================"
echo ""

# 鍵ファイルの存在確認
if [ ! -f "$KEY_FILE" ]; then
  echo "⚠️  SSH鍵が見つかりません: $KEY_FILE"
  echo "   先に 🔑SSH鍵設定.command を実行してください"
  read -p "Enterキーを押して終了..."
  exit 1
fi

echo "🔌 VPS ($VPS_IP) に接続中..."
ssh $SSH_OPTS ${VPS_USER}@${VPS_IP} "echo '接続OK'" 2>&1
if [ $? -ne 0 ]; then
  echo ""
  echo "❌ SSH接続に失敗しました"
  echo "   🔑SSH鍵設定.command を実行してから再試行してください"
  read -p "Enterキーを押して終了..."
  exit 1
fi

echo ""
echo "--- 📅 cronジョブ確認 ---"
ssh $SSH_OPTS ${VPS_USER}@${VPS_IP} "crontab -l 2>/dev/null || echo 'cronジョブなし'"

echo ""
echo "--- 📊 最新のログ（直近20行）---"
ssh $SSH_OPTS ${VPS_USER}@${VPS_IP} "ls -la ${VPS_DIR}/logs/ 2>/dev/null && tail -20 ${VPS_DIR}/logs/*.log 2>/dev/null || echo 'ログファイルなし（まだ実行されていません）'"

echo ""
echo "--- 🧪 テスト実行（dry-run）---"
echo "   Google Sheetsへの接続テストを実行します..."
ssh $SSH_OPTS ${VPS_USER}@${VPS_IP} \
  "cd ${VPS_DIR} && source venv/bin/activate && timeout 60 python3 main.py --dry-run 2>&1 | head -80"

echo ""
echo "--- 💾 ファイル確認 ---"
ssh $SSH_OPTS ${VPS_USER}@${VPS_IP} "ls -la ${VPS_DIR}/"

echo ""
echo "========================================"
echo "  確認完了"
echo "========================================"
echo ""
read -p "Enterキーを押して終了..."
