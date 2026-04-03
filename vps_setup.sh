#!/bin/bash
# ============================================================
#  vps_setup.sh  —  VPS初期セットアップ（Ubuntu 22.04 LTS）
#  ConohaVPS / さくらVPS どちらでも動作します
#
#  【実行方法】
#  VPSにSSHログイン後、このファイルをアップロードして実行：
#    bash vps_setup.sh
# ============================================================

set -e  # エラーで即停止

echo "============================================"
echo "  メルカリ×eBay 在庫監視 VPSセットアップ"
echo "============================================"

# ---- 1. システム更新 ----------------------------------------
echo ""
echo "[1/7] システム更新中..."
apt-get update -y && apt-get upgrade -y

# ---- 2. Python3・pip・必要パッケージ -----------------------
echo ""
echo "[2/7] Python環境インストール中..."
apt-get install -y python3 python3-pip python3-venv git curl wget unzip \
  libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
  libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
  libcairo2

# ---- 3. プロジェクトディレクトリ作成 ----------------------
echo ""
echo "[3/7] プロジェクト設定中..."
mkdir -p /opt/mercari_monitor
cd /opt/mercari_monitor

# Python仮想環境
python3 -m venv venv
source venv/bin/activate

# ---- 4. Pythonパッケージインストール -----------------------
echo ""
echo "[4/7] Pythonパッケージインストール中..."
pip install --upgrade pip
pip install \
  playwright \
  requests

# Playwright ブラウザ（Chromium）インストール
echo ""
echo "  Playwrightブラウザをインストール中..."
playwright install chromium
playwright install-deps chromium

# ---- 5. スクリプトのコピー確認 ----------------------------
echo ""
echo "[5/7] スクリプトファイルを確認..."
REQUIRED_FILES=("main.py" "config.py" "mercari_checker.py" "ebay_updater.py" "notifier.py" "items.csv")
ALL_OK=true
for f in "${REQUIRED_FILES[@]}"; do
  if [ ! -f "$f" ]; then
    echo "  ⚠️  未配置: $f"
    ALL_OK=false
  else
    echo "  ✅  確認: $f"
  fi
done

if [ "$ALL_OK" = false ]; then
  echo ""
  echo "  ↑ 上記ファイルをこのディレクトリ (/opt/mercari_monitor) に"
  echo "    アップロードしてからcron設定を行ってください。"
fi

# ---- 6. cron設定（1時間ごと、24時間） ----------------------
echo ""
echo "[6/7] cron設定中（1時間ごと / 24時間稼働）..."
PYTHON_PATH="/opt/mercari_monitor/venv/bin/python3"
SCRIPT_DIR="/opt/mercari_monitor"
LOG_FILE="$SCRIPT_DIR/monitor.log"

# 毎時0分に実行（24時間365日）
CRON_ENTRY="0 * * * * cd $SCRIPT_DIR && $PYTHON_PATH main.py >> $LOG_FILE 2>&1"

# 毎朝8時にリスクレポート送信
RISK_CRON="0 8 * * * cd $SCRIPT_DIR && $PYTHON_PATH risk_report.py >> $SCRIPT_DIR/logs/risk_report.log 2>&1"

# 重複を避けて追加
(crontab -l 2>/dev/null | grep -v "mercari_monitor" | grep -v "risk_report"; echo "$CRON_ENTRY"; echo "$RISK_CRON") | crontab -

echo "  ✅ cron設定完了"
echo "  スケジュール: 毎時0分（在庫監視）/ 毎朝8時（リスクレポート）"

# ---- 7. ログローテーション設定 ----------------------------
echo ""
echo "[7/7] ログローテーション設定中..."
cat > /etc/logrotate.d/mercari_monitor << 'LOGROTATE'
/opt/mercari_monitor/monitor.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
LOGROTATE

# ---- 完了 --------------------------------------------------
echo ""
echo "============================================"
echo "  ✅ セットアップ完了！"
echo "============================================"
echo ""
echo "【次のステップ】"
echo "  1. config.py にeBay APIキーを記入"
echo "  2. items.csv にメルカリURL ↔ eBay出品IDを記入"
echo "  3. 動作テスト:"
echo "     cd /opt/mercari_monitor"
echo "     source venv/bin/activate"
echo "     python3 main.py --dry-run"
echo ""
echo "【確認コマンド】"
echo "  cron確認  : crontab -l"
echo "  ログ確認  : tail -f /opt/mercari_monitor/monitor.log"
echo "  手動実行  : cd /opt/mercari_monitor && source venv/bin/activate && python3 main.py"
echo ""
