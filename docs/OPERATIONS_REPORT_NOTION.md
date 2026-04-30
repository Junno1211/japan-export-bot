# JAPAN EXPORT ボット — 運用報告書（Notion用）

> **使い方:** このファイルを Notion に「インポート → Markdown」するか、全文コピーしてページに貼り付けてください。見出しは Notion のトグルやカラムに分割しても構いません。

---

## 1. 文書の目的

本稿は、**無在庫転売（メルカリ仕入れ → eBay販売）**において、当社が日々依存している **自動化パイプライン**の全体像・責任分界・手動／自動の境界を、社内共有・引き継ぎ・監査用に整理したものです。

**最上位ルール**はリポジトリ内 `CLAUDE.md`（オークション禁止、$2,499 上限、SOLD 後の在庫戻し禁止等）。本報告書は運用レイヤーの要約であり、`CLAUDE.md` を代替しません。

---

## 2. システム構成（ざっくり）

| 区分 | 役割 |
|------|------|
| **Google スプレッドシート** | 優先出品・自動出品（AUTO）・在庫管理表。出品キューとマスタ。 |
| **auto_lister.py** | シートから読み取り、ルール・メルカリ確認経由で eBay 出品。 |
| **inventory_manager.py** | アクティブ出品のメルカリ在庫を定期確認。売切・オークション等で eBay 在庫0・シート更新。 |
| **order_monitor.py** | eBay 成約検知、Slack 通知、SOLD 記録、必要に応じて在庫0。 |
| **test_rules.py** | 出品前の自動チェック（必須）。失敗時は出品しない。 |
| **supervisor.py** | 出品・リサーチの検証（プロジェクトルール参照）。 |

---

## 3. 日次の「自動で回る」もの（cron）

Mac（または将来の VPS）の **crontab** で、次の正規行を前提としています（パスは実環境のプロジェクトルートに合わせる）。

| スケジュール（cron） | ジョブ | 意味 |
|---------------------|--------|------|
| `0 * * * *` | `inventory_manager.py`（`-u`） | **在庫管理：毎時0分** |
| `5 * * * *` | `order_monitor.py`（`-u`） | **注文監視：毎時5分**（在庫ジョブと起動を5分ずらす） |
| `0 8 * * *` | `daily_report.py` | 朝レポート |
| `0 10 * * 1,2,4,5,0` | `fill_daily_until_done.sh` | **出品70品目標**（月火木金日・日=0） |
| `0 10 * * 3,6` | `fill60_until_done.sh` | **出品60品**（水・土・従来ブースト用。要変更なら `fill_daily_until_done.sh 80` 等） |
| `0 21 4 4 *` | `auto_lister.py`（ログ名に 20260404） | **一回限りの特別 cron（必要なら残す／不要なら削除要検討）** |

**crontab の修復・正規化**

- `python3 scripts/repair_crontab_project_jobs.py --write-file=logs/crontab.new.txt` のあと `crontab logs/crontab.new.txt`
- 廃止した `cron_hourly_zero.sh` 行は修復スクリプトが削除対象

**注意（Mac）**

- 本体が **スリープ中は cron は原則動かない**（起床後に遅延実行の可能性）。**24時間必須**の場合は VPS 等の常時稼働ホストが必要。
- 長時間まとめて出品するときは **`scripts/run_fill_with_caffeinate.sh`**（内部で `caffeinate`）でスリープ抑制を検討。

---

## 4. 出品件数目標（70 / 任意ブースト）

`repair_crontab_project_jobs.py` 適用後の crontab に、**上表のとおり 10:00 JST の出品ジョブが含まれる**想定。

| スクリプト | 内容 |
|------------|------|
| `scripts/fill_daily_until_done.sh` | 引数なし → **70品**目標。`test_rules` 合格後、`auto_lister --max-success` をループ。 |
| `scripts/fill60_until_done.sh` | 内部で **60品**（明示実行用）。 |
| `scripts/run_fill_with_caffeinate.sh` | 上記を `caffeinate` 付きで実行（手動ブースト用）。 |

- 成功時: `logs/fill_daily_RESULT.txt`、異常時: `logs/fill_daily_ABORT.txt`
- 手動で回す場合: `bash scripts/fill_daily_until_done.sh` または `bash scripts/fill60_until_done.sh`

---

## 5. 在庫管理の技術フロー（要約）

1. スプレッドシートの在庫管理表から **status=active かつ URL・eBay ID あり**の行を取得。
2. **メルカリ API** で一次判定（売切・削除・オークション・active・error 等）。
3. **API が error（例: 401）** の場合でも **HTML で「購入手続きへ」相当を確認**（Playwright 共有ブラウザで負荷抑制）。
4. 売切・オークション・購入不可 → **eBay 在庫0**、シート更新、必要に応じ Slack。
5. **二重起動防止**（ロックファイル）。ログは `logs/inventory.log` および日付付きファイル。

**ビジネス上の絶対条件（再掲）**

- オークション商品は出品・仕入れ対象外。
- 売れた URL は **SOLD 記録後に在庫1へ戻さない**。

---

## 6. 注文監視（order_monitor）

- eBay **GetOrders** 系で成約を取得。
- メルカリ URL が取れる場合は在庫確認。Slack 通知、**items.csv への SOLD 記録**、eBay 在庫0 等。

---

## 7. ヘルスチェック・ログ

| コマンド / ファイル | 用途 |
|---------------------|------|
| `bash scripts/inventory_health_check.sh` | Mac crontab 抜粋、inventory.log 末尾、**VPS SSH プローブ**（鍵・ホストは `scripts/vps.env` で上書き可） |
| `bash scripts/log_health_snapshot.sh` | inventory / orders ログの末尾と警告行のざっとした一覧 |
| `logs/inventory.log` | 在庫ジョブの標準出力系 |
| `logs/orders.log` | 注文ジョブ |

---

## 8. VPS と Mac

- **VPS** が **SSH Connection refused** の間はコードでは復旧できない。**パネルで電源・FW・IP を確認**後、`bash scripts/vps_diagnose.sh` で疎通確認。
- 復旧手順の要約: `VPS_GUIDE.md`（「SSH Connection refused」の節）。cron テンプレ: `scripts/vps_cron_snippet.txt`。

---

## 8.1 実行環境（Python）

- **Python 3.10+ 推奨**（3.9 は各ライブラリの EOL 警告が出る）。可能なら Homebrew 等で上げ、`python3` を crontab と揃える。

---

## 9. API レート制限（eBay）

- **エラー 518** 等を検知した場合は **処理停止**（`CLAUDE.md`）。`fill_daily_until_done.sh` もログを grep して異常終了する設計。

---

## 10. セキュリティ（社内向け注意）

- **`config.py` / `.env` / `google_credentials.json`** は秘密情報。**リポジトリ・スクリーンショットで外部に出さない。**
- 漏えい疑いがある場合は **eBay トークン・各種 API キーのローテーション**を検討。

---

## 11. 変更履歴（本報告書の前提となった主な運用変更）

- 注文監視を **5分間隔から毎時5分**（在庫と負荷分散）に整理。
- 在庫 **毎時0分**、注文 **毎時5分** の **正規 crontab 行**に統一（`repair_crontab_project_jobs.py`）。
- 廃止スクリプト **`cron_hourly_zero.sh` 行の削除**を修復フローに組み込み。
- 出品目標 **70／水土は60等** を `repair_crontab` の正規行に含める（10:00 JST）。
- **メルカリ API が 200 以外**のときは **HTML（購入ボタン）にフォールバック**（401 対策）。
- **eBay 終了済み出品**への在庫0更新は **成功扱い**にしてログノイズを削減（`ebay_updater.py`）。
- **GetOrders** は接続 **3回リトライ**＋XML 解析エラー処理（`order_monitor.py`）。
- `scripts/vps_diagnose.sh` / `run_fill_with_caffeinate.sh` 追加。

---

## 12. 次のアクション（任意）

- [ ] `repair_crontab` 適用後 **`crontab -l`** で出品ジョブ（70/60 等）が入っているか確認。
- [ ] VPS 復旧後、`vps_diagnose.sh` → `vps_cron_snippet` で cron 再設定。
- [ ] `auto_lister_20260404` の **年1回 cron が不要なら** crontab から削除するか検討。
- [ ] **Python 3.10+** へ上げるタイミングを決める。

---

**作成方針:** 本ファイルは社内 Notion への貼り付け用であり、**実行コマンドのパスは各マシンの実パスに読み替えること。**
