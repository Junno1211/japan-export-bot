#!/usr/bin/env bash
# Mac のターミナル（プロンプトが ~ % など）でだけ実行する。
# VPS 上の root crontab を fill_daily_until_done.sh 70 に揃える（fix_crontab_fill_daily_70.sh を SSH で実行）。
#
# 使い方（この1行だけコピペ）:
#   cd "/Users/miyazakijunnosuke/Downloads/eBay/海外輸出ボット" && bash scripts/mac_fix_fill_daily_70_on_vps.sh
#
# 環境変数: VPS_IP（省略時 133.117.76.193） VPS_USER（省略時 root）
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "このスクリプトは Mac（ターミナル）専用です。いまは ConoHa など別の OS の可能性があります。" >&2
  echo "リモートだけ直すなら、次の1行を **そのマシンのターミナル**に貼ってください:" >&2
  echo "  cd /opt/export-bot && bash scripts/fix_crontab_fill_daily_70.sh" >&2
  exit 1
fi

VPS_IP="${VPS_IP:-133.117.76.193}"
VPS_USER="${VPS_USER:-root}"
REMOTE="${VPS_USER}@${VPS_IP}"

echo "● Mac から ${REMOTE} へ SSH し、出品目標 cron を 70 に揃えます。"
echo "  （パスワードを聞かれたら ConoHa の root パスワード）"
echo ""

ssh -o ServerAliveInterval=60 -o StrictHostKeyChecking=accept-new "${REMOTE}" \
  'cd /opt/export-bot && bash scripts/fix_crontab_fill_daily_70.sh && echo "---" && crontab -l | grep fill_daily_until_done'

echo ""
echo "● 完了。上に fill_daily_until_done.sh 70 の行が1本出ていれば OK です。"
