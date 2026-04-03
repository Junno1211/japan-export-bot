#!/bin/bash
# ============================================================
#  🔑SSH鍵設定.command
#  パスワード不要でSSH接続できるように設定します
#  （Homebrew不要・macOS標準のexpectを使用）
# ============================================================

cd "$(dirname "$0")"

VPS_IP="133.117.76.193"
VPS_USER="root"
VPS_PASS="***REMOVED***"
KEY_FILE="$HOME/.ssh/mercari_vps"

echo "========================================"
echo "  SSH鍵認証セットアップ"
echo "========================================"
echo ""

# ── Step 1: SSH鍵ペア生成 ──
if [ ! -f "$KEY_FILE" ]; then
  echo "🔑 SSH鍵を生成中..."
  ssh-keygen -t ed25519 -f "$KEY_FILE" -N "" -C "mercari_vps" 2>&1
  echo "✅ 鍵生成完了"
else
  echo "✅ SSH鍵は既に存在: $KEY_FILE"
fi

PUB_KEY=$(cat "${KEY_FILE}.pub")
echo ""

# ── Step 2: 古いフィンガープリントを削除 ──
ssh-keygen -R $VPS_IP 2>/dev/null

# ── Step 3: expectを使ってVPSに公開鍵を登録 ──
echo "📤 公開鍵をVPSに登録中..."

/usr/bin/expect << EXPECT_EOF
set timeout 30
spawn ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 ${VPS_USER}@${VPS_IP} "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '${PUB_KEY}' >> ~/.ssh/authorized_keys && sort -u ~/.ssh/authorized_keys -o ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo KEY_REGISTERED"
expect {
  "password:" {
    send "${VPS_PASS}\r"
    exp_continue
  }
  "KEY_REGISTERED" {
    puts "\n✅ 公開鍵登録完了！"
    exit 0
  }
  "Permission denied" {
    puts "\n❌ パスワードが違います"
    exit 1
  }
  timeout {
    puts "\n❌ タイムアウト"
    exit 1
  }
  eof {
    exit 0
  }
}
EXPECT_EOF

EXPECT_EXIT=$?

if [ $EXPECT_EXIT -ne 0 ]; then
  echo ""
  echo "❌ 公開鍵の登録に失敗しました"
  read -p "Enterキーを押して終了..."
  exit 1
fi

echo ""

# ── Step 4: 鍵認証でテスト接続 ──
echo "🧪 鍵認証でテスト接続..."
sleep 1

TEST_RESULT=$(ssh -i "$KEY_FILE" \
  -o StrictHostKeyChecking=no \
  -o ConnectTimeout=10 \
  -o PasswordAuthentication=no \
  ${VPS_USER}@${VPS_IP} \
  "echo SUCCESS && hostname && crontab -l 2>/dev/null | grep -c mercari || echo 'cron:0'" 2>&1)

if echo "$TEST_RESULT" | grep -q "SUCCESS"; then
  echo ""
  echo "========================================"
  echo "  🎉 SSH鍵設定完了！"
  echo "$TEST_RESULT"
  echo "========================================"

  # ~/.ssh/config に設定を追記
  SSH_CONFIG="$HOME/.ssh/config"
  if ! grep -q "Host mercari-vps" "$SSH_CONFIG" 2>/dev/null; then
    cat >> "$SSH_CONFIG" << EOF

Host mercari-vps
  HostName $VPS_IP
  User $VPS_USER
  IdentityFile $KEY_FILE
  StrictHostKeyChecking no
  ServerAliveInterval 10
  ServerAliveCountMax 6
EOF
    chmod 600 "$SSH_CONFIG"
    echo "✅ ~/.ssh/config を設定しました"
  fi

  echo ""
  echo "次のステップ:"
  echo "  → 📋設定を送る.command を実行して動作確認"
else
  echo ""
  echo "❌ 鍵認証テスト失敗"
  echo "エラー内容: $TEST_RESULT"
fi

echo ""
read -p "Enterキーを押して終了..."
