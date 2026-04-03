#!/bin/bash
# ============================================================
#  deploy.sh  —  ローカルMacからVPSにファイルを転送するスクリプト
#  【使い方】Mac のターミナルで実行する
#    bash deploy.sh
# ============================================================

# ▼▼▼ ここだけ自分の情報に書き換える ▼▼▼
VPS_IP="133.117.76.193"        # ConohaのIPアドレス
VPS_USER="root"                # 初期ユーザー（Conohaはroot）
VPS_DIR="/opt/mercari_monitor"
# ▲▲▲ ここまで ▲▲▲

LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "📤 VPS ($VPS_IP) にファイルを転送中..."

# ディレクトリ作成
ssh ${VPS_USER}@${VPS_IP} "mkdir -p ${VPS_DIR}"

# ファイル転送（config.pyとgoogle_credentials.jsonも含む）
scp \
  "${LOCAL_DIR}/main.py" \
  "${LOCAL_DIR}/config.py" \
  "${LOCAL_DIR}/mercari_checker.py" \
  "${LOCAL_DIR}/ebay_updater.py" \
  "${LOCAL_DIR}/sheets_manager.py" \
  "${LOCAL_DIR}/notifier.py" \
  "${LOCAL_DIR}/risk_report.py" \
  "${LOCAL_DIR}/requirements.txt" \
  "${LOCAL_DIR}/vps_setup.sh" \
  "${LOCAL_DIR}/google_credentials.json" \
  ${VPS_USER}@${VPS_IP}:${VPS_DIR}/

echo ""
echo "✅ 転送完了！"
echo ""
echo "次のコマンドでVPSにSSH接続してセットアップを実行："
echo "  ssh ${VPS_USER}@${VPS_IP}"
echo "  cd ${VPS_DIR} && bash vps_setup.sh"
