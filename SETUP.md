# メルカリ在庫監視 × eBay自動更新 セットアップガイド

## 全体の流れ

```
メルカリURL → Playwright でページ確認 → 売り切れ検知
    → eBay Trading API → Quantity=0 に更新
    → Google Sheets → ステータスを "OutOfStock" に更新
    → (任意) Slack に通知
```

---

## Step 1: Pythonパッケージのインストール

```bash
cd mercari_ebay_monitor
pip install -r requirements.txt
playwright install chromium
```

---

## Step 2: Google Sheets API の設定

1. **Google Cloud Console** (console.cloud.google.com) を開く
2. プロジェクトを作成 → **「APIとサービス」→「有効なAPIとサービス」**
3. **「Google Sheets API」** を検索して有効化
4. **「サービスアカウント」** を作成
5. キー → **「JSONキーを追加」** でダウンロード
6. ダウンロードしたファイルを `google_credentials.json` にリネームして、このフォルダに置く
7. スプレッドシートの **共有設定** → サービスアカウントのメールアドレスを「編集者」で追加

---

## Step 3: スプレッドシートのフォーマット

シート名「在庫管理」で以下の列を作成：

| A列 | B列 | C列 | D列 | E列 | F列 |
|-----|-----|-----|-----|-----|-----|
| メルカリURL | メルカリID | eBay Item ID | ステータス | 最終チェック | メモ |
| https://jp.mercari.com/item/m1234 | m1234 | 123456789012 | Active | | |

**ステータスの値:**
- `Active` = 出品中（チェック対象）
- `OutOfStock` = 在庫切れ（スキップ）
- `Ended` = 出品終了（スキップ）
- `Skip` = チェック除外

---

## Step 4: eBay API の設定

1. **eBay Developer Program** (developer.ebay.com) にログイン
2. **「Get a User Token」** から Auth Token を取得
   - Token Type: **Production**
   - 有効期限は18ヶ月なので定期更新が必要
3. `config.py` の以下を埋める：
   ```python
   EBAY_APP_ID    = "YourApp-xxxx-xxxx"
   EBAY_DEV_ID    = "xxxxxxxx-xxxx-xxxx"
   EBAY_CERT_ID   = "xxxxxxxx-xxxx-xxxx"
   EBAY_AUTH_TOKEN = "AgAAAA**..."  # 長い文字列
   ```

---

## Step 5: config.py を設定

```python
SPREADSHEET_ID = "1RfNtaqyzjpiwD4LqLbD_cPIGTj62cUorfKywPYtJ128"  # あなたのSpreadsheet ID
SHEET_NAME     = "在庫管理"
```

---

## Step 6: テスト実行

```bash
# ドライランで動作確認（eBay・シートは更新しない）
python3 main.py --dry-run

# 特定URLだけテスト
python3 main.py --single "https://jp.mercari.com/item/m12345678"

# 本番実行
python3 main.py
```

---

## Step 7: 自動実行の設定（cron）

```bash
bash cron_setup.sh
```

これで毎日 6〜20時の間、2時間おきに自動チェックが走ります。

ログ確認：
```bash
tail -f monitor.log
```

---

## トラブルシューティング

### メルカリのチェックが全部 "error" になる
→ Playwright のブラウザが正しくインストールされているか確認
```bash
playwright install chromium
```

### eBay API が "Invalid token" エラー
→ Auth Token の有効期限が切れている。eBay Developer Portal で再取得。

### Google Sheets に書き込めない
→ サービスアカウントのメールアドレスがシートに「編集者」で共有されているか確認。

---

## セキュリティ注意事項

⚠️ `config.py` と `google_credentials.json` は **絶対に GitHub にアップロードしない！**

`.gitignore` に以下を追加：
```
config.py
google_credentials.json
*.log
```
