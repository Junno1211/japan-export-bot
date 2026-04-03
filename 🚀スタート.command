#!/bin/bash
# ============================================================
#  🚀スタート.command
#  VPSにファイルを転送してセットアップを実行します
#  ★ 初回のみ。2回目以降は不要です ★
# ============================================================

cd "$(dirname "$0")"

VPS_IP="133.117.76.193"
VPS_USER="root"
VPS_DIR="/opt/mercari_monitor"
KEY_FILE="$HOME/.ssh/mercari_vps"
VPS_PASS="***REMOVED***"

echo "========================================"
echo "  メルカリ在庫監視システム セットアップ"
echo "========================================"
echo ""

# SSH鍵があれば鍵認証、なければパスワード認証
if [ -f "$KEY_FILE" ]; then
  SSH_OPTS="-i $KEY_FILE -o StrictHostKeyChecking=no -o ConnectTimeout=30 -o PasswordAuthentication=no"
  SCP_OPTS="-i $KEY_FILE -o StrictHostKeyChecking=no"
  echo "🔑 SSH鍵認証で接続します"
else
  SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=30 -o ServerAliveInterval=10 -o ServerAliveCountMax=6"
  SCP_OPTS="-o StrictHostKeyChecking=no"
  echo "🔐 パスワード認証で接続します"
  echo "   → パスワードを聞かれたら: $VPS_PASS"
fi

echo ""

# 古いSSHフィンガープリントを削除
ssh-keygen -R ${VPS_IP} 2>/dev/null

echo "📤 VPS ($VPS_IP) にファイルを転送中..."
echo ""

# VPSにディレクトリ作成
ssh $SSH_OPTS ${VPS_USER}@${VPS_IP} "mkdir -p ${VPS_DIR}"

# ファイル転送
scp $SCP_OPTS \
  main.py \
  config.py \
  mercari_checker.py \
  ebay_updater.py \
  notifier.py \
  requirements.txt \
  items.csv \
  vps_setup.sh \
  ${VPS_USER}@${VPS_IP}:${VPS_DIR}/

if [ $? -ne 0 ]; then
  echo ""
  echo "❌ ファイル転送に失敗しました"
  echo "   パスワードが正しいか確認してください: $VPS_PASS"
  read -p "Enterキーを押して終了..."
  exit 1
fi

echo ""
echo "✅ ファイル転送完了！"
echo ""
echo "========================================"
echo "  VPSでセットアップを実行中..."
echo "  （数分かかります）"
echo "========================================"
echo ""

# VPSに接続してセットアップ自動実行
ssh $SSH_OPTS -t ${VPS_USER}@${VPS_IP} \
  "cd ${VPS_DIR} && bash vps_setup.sh && echo '✅ セットアップ完了！'"

echo ""
echo "========================================"
echo "  🎉 完了！毎時間自動で在庫チェック開始"
echo "========================================"
echo ""
echo "  次のステップ:"
echo "  1. 🔑SSH鍵設定.command を実行してSSH鍵認証を設定"
echo "  2. 🧪テスト実行.command で動作確認"
echo ""
read -p "Enterキーを押して終了..."
