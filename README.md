# eBay海外輸出ボット

メルカリ仕入れ → eBay自動出品・在庫同期システム

## 全体フロー

```
[リサーチ]                    [出品]                     [在庫管理]
auto_sourcer.py               auto_lister.py              main.py (1時間ごと自動)
  ↓                             ↓                          ↓
メルカリ検索                   スプレッドシートから取得      メルカリ在庫チェック
  ↓                             ↓                          ↓
eBay相場確認                   Gemini AIでタイトル最適化    売り切れ検知
  ↓                             ↓                          ↓
採算判定(ROI25%/利益¥3,000+)   eBay APIで出品              eBay在庫0に自動変更
  ↓                             ↓                          ↓
スプレッドシートに候補追加      在庫管理表に登録            スプレッドシート更新
```

## スプレッドシート構成

| シート名 | 用途 |
|---|---|
| 在庫管理表 | 出品中の全商品（eBay ID ↔ メルカリURL） |
| 優先出品 | 手動で追加した出品候補 |
| 自動出品_カード | カード系リサーチ結果（ワンピ・ポケモン・大谷等） |
| 自動出品_ホビー | ホビー系リサーチ結果（ガンダム・漫画・グッズ） |
| 自動出品_その他 | その他リサーチ結果（時計・携帯・雑貨） |
| 検索キーワード | リサーチ用キーワード一覧 |

## セットアップ（新規導入）

### 事前準備

1. **eBay開発者アカウント** — https://developer.ebay.com
   - App ID / Dev ID / Cert ID / Auth Token を取得
2. **Google Cloud Console** — https://console.cloud.google.com
   - Sheets API を有効化
   - サービスアカウント作成 → JSONキーをダウンロード
   - スプレッドシートを作成し、サービスアカウントのメールアドレスに編集権限を付与
3. **Gemini API** — https://aistudio.google.com
   - APIキーを取得
4. **Slack Webhook**（任意） — https://api.slack.com/messaging/webhooks

### インストール

```bash
bash setup.sh
```

対話形式でAPIキーを入力すると、config.py生成 + パッケージインストール + スプレッドシート初期化まで自動で完了します。

### 動作確認

```bash
# 在庫監視テスト（eBayに変更は加えない）
python3 main.py --dry-run

# 自動出品テスト
python3 auto_lister.py --dry-run

# リサーチ実行
python3 auto_sourcer.py
```

### 自動実行の設定

```bash
bash cron_setup.sh
```

在庫監視が1時間ごとに自動実行されます。

## 主要スクリプト

| スクリプト | 役割 |
|---|---|
| `main.py` | メルカリ売り切れ監視 → eBay在庫0 |
| `auto_lister.py` | スプレッドシートから自動出品 |
| `auto_sourcer.py` | メルカリ → eBay相場比較 → リサーチ候補作成 |
| `inventory_sync.py` | メルカリ ↔ eBay在庫同期 |
| `restock_recovery.py` | メルカリ復活時にeBay在庫復帰 |
| `daily_report.py` | 日次レポート（Slack通知） |
| `ebay_lister.py` | eBay出品API |
| `ebay_updater.py` | eBay在庫更新API |
| `mercari_scraper.py` | メルカリ商品情報取得 |
| `sheets_manager.py` | Google Sheets読み書き |

## ビジネスルール

- 手数料合計: 19.6%（FVF 13.25% + 海外 1.35% + Payoneer 2% + Promoted 3%）
- 為替: 155 JPY/USD
- 消費税還付: 10%
- 目標: ROI 25% or 利益 ¥3,000〜5,000
- SHIPPING WORLDWIDE 必須

## 注意

- `config.py` と `google_credentials.json` には秘密情報が含まれます。外部に公開しないでください。
- eBay Auth Token は定期的に期限切れになります。更新手順はeBay Developer Programを参照。
