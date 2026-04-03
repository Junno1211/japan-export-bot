# VPS 24時間自動巡回 セットアップガイド

## おすすめVPS比較

| サービス | プラン | 月額 | RAM | 推奨度 |
|---------|--------|------|-----|--------|
| **ConohaVPS** | 2GBプラン | ¥1,320 | 2GB | ◎ 一番おすすめ |
| **さくらVPS** | 2GBプラン | ¥1,188 | 2GB | ◎ |
| **Vultr** | Regular 2GB | $12 | 2GB | ○ 英語だが高品質 |

> **Playwright（ブラウザ自動化）は最低1GB RAM必要。2GBが安定。**

---

## Step 1: ConohaVPS を契約する

1. [ConohaVPS](https://www.conoha.jp/vps/) にアクセス
2. 会員登録 → クレジットカード登録
3. **「VPS追加」** をクリック
4. 設定：
   - **イメージ**: Ubuntu 22.04 LTS
   - **プラン**: 2GB（月額¥1,320）
   - **rootパスワード**: 自分で設定（必ず記録しておく）
5. 「追加」→ 数分でIPアドレスが発行される

---

## Step 2: MacからVPSに接続

```bash
# ターミナルを開いて
ssh root@あなたのIPアドレス

# パスワードを入力（上で設定したrootパスワード）
```

---

## Step 3: ファイルをVPSに転送

Macのターミナルで（VPSにはまだ接続しない状態で）：

```bash
# deploy.sh の VPS_IP を自分のIPアドレスに書き換えてから
cd /path/to/mercari_ebay_monitor
bash deploy.sh
```

---

## Step 4: VPSでセットアップ実行

```bash
# VPSにSSH接続して
ssh root@あなたのIPアドレス

# セットアップスクリプトを実行（全部自動でインストールされる）
cd /opt/mercari_monitor
bash vps_setup.sh
```

所要時間：約5〜10分

---

## Step 5: config.py にAPIキーを記入

```bash
# VPS上でエディタを開く
nano /opt/mercari_monitor/config.py
```

以下を自分の情報に書き換える：
```python
SPREADSHEET_ID  = "あなたのSpreadsheetID"
EBAY_APP_ID     = "あなたのAPP_ID"
EBAY_AUTH_TOKEN = "あなたのAuthToken"
```

保存：`Ctrl+X` → `Y` → `Enter`

---

## Step 6: 動作テスト

```bash
cd /opt/mercari_monitor
source venv/bin/activate

# まずドライランで確認
python3 main.py --dry-run

# 問題なければ本番実行
python3 main.py
```

---

## 巡回スケジュール（設定済み）

```
毎時0分 = 1時間ごと、24時間365日稼働
00:00 / 01:00 / 02:00 / ... / 22:00 / 23:00
```

確認コマンド：
```bash
crontab -l
# → 0 * * * * cd /opt/mercari_monitor && ... が表示されればOK
```

---

## ログ確認（リアルタイム）

```bash
tail -f /opt/mercari_monitor/monitor.log
```

出力例：
```
2026-03-18 02:00:01 [INFO] 🚀 在庫監視 開始
2026-03-18 02:00:01 [INFO] シートから 47 件のアクティブアイテムを読み込みました
2026-03-18 02:00:03 [INFO] [1/47] eBay:123456789012
2026-03-18 02:00:05 [INFO]   ✅ 在庫あり: PSA10 ポケモン ピカチュウ...
2026-03-18 02:00:08 [INFO] [2/47] eBay:234567890123
2026-03-18 02:00:10 [INFO]   ❌ 売り切れ検知 → eBay更新: 234567890123
2026-03-18 02:00:11 [INFO]   ✅ eBay Item 234567890123 → quantity=0 に更新成功
```

---

## コスト まとめ

| 項目 | 月額 |
|------|------|
| ConohaVPS 2GB | ¥1,320 |
| Claude Maxプラン | $100（¥15,930） |
| Google Workspace | ¥900 |
| **合計** | **約¥18,150/月** |

> キャンセル1件防ぐだけで元が取れる。在庫切れによるアカウント健全性悪化も防止。

---

## よくある質問

**Q: VPSが止まったらどうなる？**
→ Conohaは99.99%の稼働率保証。万が一止まっても自動で再起動される。cronはOS起動時に自動復帰。

**Q: セキュリティは大丈夫？**
→ rootパスワードを強力なものにすれば基本OK。気になるならSSH鍵認証に変更推奨。

**Q: 途中でスクリプトを更新したい場合は？**
→ Macで修正 → `bash deploy.sh` で再転送 → VPSで自動的に新しいコードが実行される。
