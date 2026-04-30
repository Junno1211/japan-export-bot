# eBay海外輸出ボット — JAPAN EXPORT

メルカリで仕入れ → eBayで自動出品 → 在庫自動管理のシステムです。
パソコンを閉じていても24時間自動で動きます。

### 設計・戦略ドキュメント

- [事業モデル刷新仕様書 v1.0](docs/JAPAN_EXPORT_MODEL_REFRESH_v1.md)
- [Phase 0 チェックリスト](docs/PHASE_0_CHECKLIST.md)（Phase 1 着手前の前提条件）

---

## 全体の流れ

```
メルカリで商品を探す → eBayに自動出品 → 売れたらメルカリで購入して発送
       ↑                    ↑                    ↑
  auto_sourcer.py       auto_lister.py      order_monitor.py
  （自動リサーチ）       （自動出品）         （注文監視）

在庫管理: inventory_manager.py が毎時間メルカリの在庫をチェック
          売り切れたらeBayを自動停止（二重販売防止）
```

---

## セットアップ手順（ゼロから始める人向け）

### ステップ1: 必要なアカウントを準備する

以下の4つのアカウントが必要です。全て無料で作成できます。

| サービス | 用途 | 取得先 |
|---------|------|--------|
| eBay開発者アカウント | eBayに自動出品するため | https://developer.ebay.com |
| Googleサービスアカウント | スプレッドシートを操作するため | https://console.cloud.google.com |
| Gemini APIキー | 商品タイトルの英語翻訳のため | https://aistudio.google.com |
| Slackワークスペース | 通知を受け取るため | https://slack.com |

#### 1-1. eBay開発者アカウント
1. https://developer.ebay.com にアクセス
2. 「Register」からアカウント作成
3. 「Application Keys」ページで以下を取得:
   - **App ID**（Client ID）
   - **Dev ID**
   - **Cert ID**（Client Secret）
4. 「User Tokens」から **Auth Token** を取得（Production用）

#### 1-2. Googleサービスアカウント
1. https://console.cloud.google.com にアクセス
2. 新しいプロジェクトを作成
3. 「APIとサービス」→「ライブラリ」→ **Google Sheets API** を有効化
4. 「APIとサービス」→「認証情報」→「サービスアカウント」を作成
5. 作成したサービスアカウントの「鍵」タブ → **JSON形式で鍵をダウンロード**
6. ダウンロードしたファイルを `google_credentials.json` にリネーム

#### 1-3. Gemini APIキー
1. https://aistudio.google.com にアクセス
2. 「Get API Key」→ APIキーを作成してコピー

#### 1-4. Slack Webhook URL
1. https://api.slack.com/apps でアプリ作成
2. 「Incoming Webhooks」を有効化
3. 通知を送りたいチャンネルのWebhook URLをコピー

---

### ステップ2: VPSを契約する（24時間稼働に必要）

VPS = 24時間動き続けるクラウド上のパソコンです。
パソコンを閉じてもボットが動き続けます。

#### おすすめVPS
- **ConoHa VPS** — https://www.conoha.jp （月1,000円〜）
- **さくらVPS** — https://vps.sakura.ad.jp （月800円〜）

#### 契約手順（ConoHaの場合）
1. ConoHa公式サイトでアカウント作成
2. 「VPS」→「サーバー追加」
3. プラン: **1GBプラン**（月1,000円程度）で十分
4. OS: **Ubuntu 22.04** を選択
5. rootパスワードを設定（メモしておく）
6. サーバーが起動したら **IPアドレス** をメモ

---

### ステップ3: VPSに接続する

Macの「ターミナル」アプリを開いて以下を入力:

```bash
ssh root@（VPSのIPアドレス）
```

例: `ssh root@133.117.76.193`

パスワードを聞かれたら、ステップ2で設定したrootパスワードを入力。

---

### ステップ4: ボットをインストールする

VPSに接続した状態で、以下のコマンドを**1行ずつ**コピー&ペーストして実行:

```bash
# 1. システム更新
apt update -y && apt upgrade -y

# 2. 必要なソフトをインストール
apt install -y python3 python3-pip python3-venv git curl

# 3. ボットのコードをダウンロード
git clone https://github.com/Junno1211/japan-export-bot.git /opt/bot
cd /opt/bot

# 4. Python仮想環境を作成
python3 -m venv venv
source venv/bin/activate

# 5. 必要なパッケージをインストール
pip install -r requirements.txt

# 6. Playwrightブラウザをインストール（メルカリのスクレイピングに必要）
playwright install chromium
playwright install-deps chromium
```

---

### ステップ5: 設定ファイルを作成する

```bash
# セットアップスクリプトを実行（対話形式でAPIキーを入力）
bash setup.sh
```

質問に答えていくと、`config.py` と `.env` が自動で作成されます。

または手動で作成する場合:

```bash
# .envファイルを作成
cp .env.sample .env
nano .env
```

以下の項目を入力:
```
EBAY_APP_ID=（eBayのApp ID）
EBAY_DEV_ID=（eBayのDev ID）
EBAY_CERT_ID=（eBayのCert ID）
EBAY_AUTH_TOKEN=（eBayのAuth Token）
GEMINI_API_KEY=（GeminiのAPIキー）
GOOGLE_CREDENTIALS_PATH=./google_credentials.json
SPREADSHEET_ID=（GoogleスプレッドシートのID）
SLACK_WEBHOOK_URL=（SlackのWebhook URL）
```

`google_credentials.json` もVPSにアップロード:
```bash
# Macのターミナル（別タブ）から実行
scp google_credentials.json root@（VPSのIP）:/opt/bot/
```

---

### ステップ6: Googleスプレッドシートを準備する

1. Googleスプレッドシートを新規作成
2. サービスアカウントのメールアドレス（`xxx@xxx.iam.gserviceaccount.com`）に**編集権限**を付与
3. スプレッドシートのURLからIDをコピー
   - URL: `https://docs.google.com/spreadsheets/d/ここがID/edit`
4. `.env` の `SPREADSHEET_ID` にIDを設定

---

### ステップ7: 動作確認する

```bash
cd /opt/bot
source venv/bin/activate

# テスト実行（eBayに変更は加えない）
python3 auto_lister.py --dry-run

# 在庫チェックテスト
python3 inventory_manager.py
```

エラーが出なければOKです。

---

### ステップ8: 自動実行を設定する（cron）

```bash
crontab -e
```

以下を貼り付けて保存:
```
# 在庫管理（毎時0分）
0 * * * * cd /opt/bot && /opt/bot/venv/bin/python3 -u inventory_manager.py >> logs/inventory.log 2>&1

# 注文監視（毎時5分・在庫ジョブと起動をずらす）
5 * * * * cd /opt/bot && /opt/bot/venv/bin/python3 -u order_monitor.py >> logs/orders.log 2>&1

# 毎朝レポート（8時）
0 8 * * * cd /opt/bot && /opt/bot/venv/bin/python3 daily_report.py >> logs/daily_report.log 2>&1
```

保存方法: `Ctrl+X` → `Y` → `Enter`

---

### ステップ9: 完了！

これでボットが24時間自動で動きます。

- **在庫管理**: 毎時間、メルカリの在庫を自動チェック
- **注文監視**: 毎時5分、新しい注文をSlackに通知（通知は最大約1時間遅れうる）
- **朝レポート**: 毎朝8時、売上・在庫状況をSlackに送信

---

## 日常の使い方

### 商品を出品したい場合
1. メルカリで売れそうな商品を見つける
2. スプレッドシートの「優先出品」タブにURLと期待利益を入力
3. `auto_lister.py` が自動で出品してくれる

### 自動リサーチを実行したい場合
```bash
cd /opt/bot && source venv/bin/activate
python3 auto_sourcer.py
```

### 状態を確認したい場合
```bash
# 最新のログを見る
tail -50 logs/inventory.log

# cron設定を確認
crontab -l
```

---

## Shipping Policy マップのデプロイ前チェック

出品価格の $50 刻みごとに **Trading API 用の Shipping Profile ID**（数値）が `config.py` 経由の `SHIPPING_POLICY_MAP` に必要です。欠けると「価格帯 Shipping 未設定」相当で停止します。**デプロイ前**に次を実行してください。

```bash
cd "/path/to/海外輸出ボット"
python3 scripts/check_shipping_policy_map.py
```

**サンプル出力（エラーなし）**

```text
--- OK: ERROR 0 件、WARNING 3 件 ---
```

`WARNING` は同一 Profile ID が複数の bracket_key に使われているとき（設定の前方埋めの継ぎ足し）に出ます。Seller Hub の band ごとの実 ID と一致しているか確認してください。`ERROR:` 行がある場合は終了コード 1 です。

また、`select_shipping_policy` の**初回呼び出し**時にも同様の検証が行われ、`ERROR` が残っていると例外で停止します（誤出品防止）。

### 本命: band ごとに Seller Hub の Profile ID を作り込む（前方埋めの解消）

前方埋めだけでは **複数 bracket が同一 Profile ID を共有**し、実送料が Seller Hub の意図とズレることがあります。**config.py はツールが自動では書き換えない**（ID 取り違え防止）。手順は次のとおりです。

1. **Seller Hub（Business policies → Shipping / Fulfillment）** で、価格帯ごとに別ポリシーを作る。ポリシー**名**は `shipping_policy_select.policy_label_for_bracket` と揃える（例: `$700–$749`）。命名の根拠は `shipping_policy_select.py` の `policy_label_for_bracket` / `parse_band_from_policy_name` と `test_rules.py` の shipping テスト。
2. **Mac** でリポジトリに `cd` し、TSV を取得（**トークンをログやチャットに貼らない**）:
   ```bash
   cd "/Users/miyazakijunnosuke/Downloads/eBay/海外輸出ボット"
   python3 scripts/dump_shipping_policies.py > policies.tsv
   ```
   ※ Sell Account API が **401** のときは、Trading 用 IAF トークンでは REST が通らない場合があります。eBay Developer の手順で、Account API 用の **OAuth ユーザーアクセストークン** を取得し、`.env` の **ユーザー向けトークン**として利用可能なキーに設定してください（具体的なキー名・スコープは eBay 公式ドキュメントに従う）。
3. **検証**（ERROR 0 になるまで config の手編集を繰り返す）:
   ```bash
   python3 scripts/validate_shipping_policy_map.py policies.tsv
   ```
4. **更新案の参照**: `scripts/proposed_shipping_policy_base_patch.md` の diff 雛形と注意書きを見ながら、`_SHIPPING_POLICY_BASE` を **手で** 編集する（プレースホルダを TSV の ID に置換）。
5. **デプロイ**（例）:
   ```bash
   HOST=root@133.117.76.193
   BASE="/Users/miyazakijunnosuke/Downloads/eBay/海外輸出ボット"
   scp "$BASE/config.py" "$HOST:/opt/export-bot/"
   scp "$BASE/scripts/dump_shipping_policies.py" "$HOST:/opt/export-bot/scripts/"
   scp "$BASE/scripts/validate_shipping_policy_map.py" "$HOST:/opt/export-bot/scripts/"
   scp "$BASE/scripts/proposed_shipping_policy_base_patch.md" "$HOST:/opt/export-bot/scripts/"
   ```

手動キュー（スプレッドシート「手動」タブ）の cron 運用・停止・再開は [docs/manual_listing_operations.md](docs/manual_listing_operations.md) を参照してください。

---

## 主要ファイル一覧

| ファイル | 役割 |
|---------|------|
| `auto_lister.py` | スプレッドシートから自動出品 |
| `auto_sourcer.py` | メルカリ自動リサーチ |
| `inventory_manager.py` | 在庫管理（毎時間自動） |
| `order_monitor.py` | 注文監視（毎時5分、cron は `scripts/repair_crontab_project_jobs.py` で整備可） |
| `daily_report.py` | 毎朝レポート |
| `mercari_scraper.py` | メルカリ商品情報取得 |
| `mercari_checker.py` | メルカリ在庫チェック |
| `ebay_lister.py` | eBay出品API |
| `ebay_updater.py` | eBay在庫更新API |
| `sheets_manager.py` | Google Sheets読み書き |
| `config.py` | 設定ファイル（自動生成） |
| `test_rules.py` | 出品前ルールチェック |

---

## 注意事項

- `config.py` と `google_credentials.json` には秘密情報が含まれます。**絶対に外部に公開しないでください**
- eBay Auth Tokenは定期的に期限切れになります。更新はeBay Developer Programで行います
- VPSの料金は毎月発生します。使わない場合はVPSを停止してください
- **Mac** はスリープ中は **cron も launchd も原則動きません**（起床後に遅れて走ることがある）。24時間監視は **VPS** か **スリープしない機器** が必要。cron の代わりに launchd を使う場合は `scripts/macos/install_launchd_export_bot.sh`（登録後は cron の同種行を削除して二重実行を避ける）
- ログのざっとした健全性: `bash scripts/log_health_snapshot.sh` / VPS 疎通: `bash scripts/inventory_health_check.sh`
