#!/bin/bash
# ============================================================
#  cron_setup.sh  —  自動実行スケジュール設定
# ============================================================
#  このスクリプトを実行すると、1時間ごとに自動で在庫チェックが走る
#  実行方法: bash cron_setup.sh
# ============================================================

# スクリプトのディレクトリを取得
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_PATH="$(which python3)"
LOG_FILE="$SCRIPT_DIR/cron.log"

echo "📁 スクリプトパス: $SCRIPT_DIR"
echo "🐍 Pythonパス: $PYTHON_PATH"

# crontab に追加するエントリ
# 毎日 6時〜21時まで1時間ごとに実行
CRON_ENTRY="0 6-21 * * * cd $SCRIPT_DIR && $PYTHON_PATH main.py >> $LOG_FILE 2>&1"

echo ""
echo "追加するcronエントリ:"
echo "  $CRON_ENTRY"
echo ""

# 既存のcrontabに追加
(crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -

echo "✅ cron設定完了！"
echo ""
echo "確認コマンド: crontab -l"
echo "ログ確認    : tail -f $LOG_FILE"
echo ""
echo "手動実行テスト:"
echo "  cd $SCRIPT_DIR && python3 main.py --dry-run"
