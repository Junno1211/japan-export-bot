#!/bin/bash
# ============================================================
#  setup.sh — eBay海外輸出ボット 初期セットアップ
#  このスクリプトを実行するだけで環境構築が完了します
# ============================================================

set -e

echo ""
echo "=========================================="
echo "  eBay海外輸出ボット セットアップ"
echo "=========================================="
echo ""

# ---- Python チェック ----
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3が見つかりません。先にインストールしてください。"
    echo "   Mac: brew install python3"
    exit 1
fi
echo "✅ Python3: $(python3 --version)"

# ---- パッケージインストール ----
echo ""
echo "📦 必要なパッケージをインストール中..."
pip3 install -q requests playwright gspread python-dotenv \
    google-api-python-client google-auth google-auth-oauthlib \
    google-auth-httplib2 google-generativeai beautifulsoup4 \
    deep_translator curl_cffi 2>/dev/null

echo "🌐 Playwrightブラウザをインストール中..."
python3 -m playwright install chromium 2>/dev/null

echo "✅ パッケージインストール完了"

# ---- API設定 ----
echo ""
echo "=========================================="
echo "  API設定（各自のキーを入力）"
echo "=========================================="
echo ""

# eBay
echo "【1/4】eBay API（https://developer.ebay.com で取得）"
read -p "  App ID (Client ID): " EBAY_APP_ID
read -p "  Dev ID: " EBAY_DEV_ID
read -p "  Cert ID (Client Secret): " EBAY_CERT_ID
echo "  Auth Token（長い文字列を貼り付け）:"
read -p "  > " EBAY_AUTH_TOKEN

# Google
echo ""
echo "【2/4】Google Sheets API"
echo "  google_credentials.json を取得して、このフォルダに配置してください。"
echo "  取得方法: Google Cloud Console → APIとサービス → 認証情報 → サービスアカウント"
read -p "  配置したらEnterを押してください... "

if [ ! -f "google_credentials.json" ]; then
    echo "⚠️  google_credentials.json が見つかりません。後で配置してください。"
fi

read -p "  スプレッドシートID: " SPREADSHEET_ID

# Gemini
echo ""
echo "【3/4】Gemini API（https://aistudio.google.com で取得）"
read -p "  Gemini API Key: " GEMINI_API_KEY

# Slack（任意）
echo ""
echo "【4/4】Slack通知（任意・スキップ可）"
read -p "  Slack Webhook URL（不要ならEnter）: " SLACK_URL
if [ -z "$SLACK_URL" ]; then
    SLACK_URL="https://hooks.slack.com/services/PLACEHOLDER"
fi

# ---- config.py 生成 ----
echo ""
echo "⚙️  config.py を生成中..."

cat > config.py << PYEOF
# ============================================================
#  config.py — 設定ファイル（自動生成）
#  このファイルは外部に公開しないこと
# ============================================================

# ---- eBay API 認証情報 ------------------------------------
EBAY_APP_ID     = "${EBAY_APP_ID}"
EBAY_DEV_ID     = "${EBAY_DEV_ID}"
EBAY_CERT_ID    = "${EBAY_CERT_ID}"
EBAY_AUTH_TOKEN = "${EBAY_AUTH_TOKEN}"
EBAY_SITE_ID    = "0"  # 0=US
EBAY_ENV = "production"

# ---- Google Sheets API ------------------------------------
GOOGLE_CREDENTIALS_PATH = "./google_credentials.json"
SPREADSHEET_ID = "${SPREADSHEET_ID}"
SHEET_NAME = "在庫管理表"

# スプレッドシートの列定義 (0始まり)
COL_EBAY_ITEM_ID = 0      # A列
COL_MERCARI_ID = -1
COL_MERCARI_URL = 3        # D列
COL_STATUS = 5             # F列
COL_LAST_CHECKED = 4       # E列
COL_NOTES = 6              # G列
DATA_START_ROW = 2

# ---- Gemini AI API ----------------------------------------
GEMINI_API_KEY = "${GEMINI_API_KEY}"

# ---- 出品シート --------------------------------------------
LISTING_SHEET_NAME = "自動出品"
PRIORITY_SHEET_NAME = "優先出品"
AUTO_SHEET_NAME = "自動出品"
AUTO_SHEET_CARD = "自動出品_カード"
AUTO_SHEET_HOBBY = "自動出品_ホビー"
AUTO_SHEET_OTHER = "自動出品_その他"
AUTO_SHEETS = [AUTO_SHEET_CARD, AUTO_SHEET_HOBBY, AUTO_SHEET_OTHER]

# ---- 通知 --------------------------------------------------
SLACK_WEBHOOK_URL = "${SLACK_URL}"
SLACK_WEBHOOK_URL_ORDERS = "${SLACK_URL}"

# ---- 監視リスト ---------------------------------------------
ITEMS_CSV_PATH = "./items.csv"
REQUEST_DELAY_SEC = 2.0

# ---- 利益計算 -----------------------------------------------
EXCHANGE_RATE = 155.0
SHIPPING_COST_JPY = 3000

# ---- シッピングポリシーID ------------------------------------
SHIPPING_POLICY_MAP = {
    0:    "",  # 各自のポリシーIDを設定
}
SHIPPING_POLICY_DEFAULT = ""  # 各自設定
PYEOF

echo "✅ config.py 生成完了"

# ---- スプレッドシート初期化 ----
echo ""
echo "📊 スプレッドシートのシートを作成中..."
python3 -c "
from sheets_manager import create_sheet_if_not_exists
sheets = ['在庫管理表', '自動出品', '優先出品', '自動出品_カード', '自動出品_ホビー', '自動出品_その他', '検索キーワード']
for s in sheets:
    try:
        create_sheet_if_not_exists(s)
        print(f'  ✅ {s}')
    except Exception as e:
        print(f'  ⚠️  {s}: {e}')
" 2>/dev/null || echo "  ⚠️  スプレッドシート初期化はgoogle_credentials.json配置後に再実行してください"

# ---- items.csv 作成 ----
if [ ! -f "items.csv" ]; then
    echo "mercari_url,ebay_item_id,memo" > items.csv
    echo "✅ items.csv 作成"
fi

# ---- cron設定 ----
echo ""
read -p "在庫監視を自動実行しますか？(y/n): " SETUP_CRON
if [ "$SETUP_CRON" = "y" ]; then
    bash cron_setup.sh
fi

# ---- 完了 ----
echo ""
echo "=========================================="
echo "  ✅ セットアップ完了！"
echo "=========================================="
echo ""
echo "次のステップ:"
echo "  1. eBayでシッピングポリシーを作成し、config.pyのSHIPPING_POLICY_MAPにIDを設定"
echo "  2. テスト実行: python3 main.py --dry-run"
echo "  3. 自動出品テスト: python3 auto_lister.py --dry-run"
echo "  4. リサーチ開始: python3 auto_sourcer.py"
echo ""
echo "問題があれば config.py を確認してください。"
