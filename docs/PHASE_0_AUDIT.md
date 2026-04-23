# Phase 0 Step 1 — コード棚卸し（監査記録）

実施日: 2026-04-17（リポジトリ静的読取）。**VPS 実 `crontab -l`**: 2026-04-21 に SSH 接続を試行したが **認証失敗のため未取得**（下記「VPS crontab」参照）。

## 用語

**確定判定**  
「売れた」「在庫なし（OOS 相当）」「処理エラー」と **ビジネスロジック上断定** し、在庫・出品・シート更新・候補除外へ反映しうる分岐。

**retry**  
同一処理に対する明示的リトライ（回数上限・バックオフ、`for attempt in range(n)` 等）。ページング間の `sleep` のみは retry とみなさない。

**独立系統の有無**（`PHASE_0_CHECKLIST.md` に定義が無いため本監査で定義）  
同一利害（**eBay 在庫 0 / メルカリ売切扱い**）に対し、**別プロセス・別エントリポイント・別設定フラグ**で結論を出しうる場合に「有」。cron で複数ジョブが走ると **片方だけ OOS** や **二重 `mark_out_of_stock`** のリスクがある。

---

## mercari_checker.py：v1 / v2 の併走（※ファイル内に「v3」という版ラベルはない）

| 系統 | 概要 | 確定判定の主箇所 |
|------|------|------------------|
| **v1 系** | `check_mercari_status`（API）→ 必要時 `_check_by_html` / `_html_buy_button_result` / `html_verify_urls` | API `sold_out` / `deleted` / `auction`、HTML `active` vs `sold_out`、`html_error` / `error` |
| **v2 系** | `mercari_head_stage1` + `_mercari_oos_playwright_stage2_only` + `mercari_oos_verdict_pass1/2` + pending JSON | HEAD 404=`deleted` 確定、DOM `sold_strict`→`sold_tentative`（二段で OOS）、auction、タイムアウトは `ambiguous` |

**`inventory_manager.py`** が `INVENTORY_MERCARI_OOS_V2` で **同一実行内では v2 か従来（HTML+API）かを排他選択**。  
**`scripts/inventory_manager_v3.py`** は **Playwright + `page.evaluate`** が主系統で、二系統突合用に `mercari_checker.check_mercari_status` / `_mercari_api_item_snapshot_no_html` を import（在庫本流の `inventory_manager.py` は変更しない）。**「v3」は mercari_checker の版ラベルではなく在庫 v3 スクリプトを指す**。

**補足:** `_check_auction_by_playwright`（`page.goto` 30000ms）は定義のみで、本リポジトリ内に **参照箇所は grep 上ゼロ**（デッドコードに近い）。

---

## 監査表（主要ファイル）

| ファイル | 行番号 | 確定判定内容 | retry有無 | 独立系統の有無 | 対応要否 |
|----------|--------|--------------|-----------|----------------|----------|
| `mercari_checker.py` | 109–110 | API 404 → **`deleted` 確定** | 無 | v1 系 | 運用と整合確認 |
| `mercari_checker.py` | 120–132 | API でオークション条件成立 → **`auction` 確定** | 無 | v1 系 | `num_bids>0` 等の偽陽性リスクはコメント参照 |
| `mercari_checker.py` | 135–139 | API `sold_out`/`trading`/`stop` → **`sold_out` 確定** | 無 | v1 系 | 同上 |
| `mercari_checker.py` | 144–149 | `Timeout`/`Exception` → **`status: error`**（売切にしない） | 無 | — | Phase 0 と整合（維持） |
| `mercari_checker.py` | 50 | オークション補助用 Playwright：`goto` **30000ms**（戻りは bool のみ） | 無 | 未使用関数 | デッドコード整理の検討 |
| `mercari_checker.py` | 157–193 | `_html_buy_button_result`：`goto` **30000ms**。購入 CTA なし → **`sold_out` 確定** | ワーカー `result(timeout=120)` のみ | v1 系 | **要検討**: 遅延描画と売切の区別 |
| `mercari_checker.py` | 271 | `html_verify_urls` 各 URL で上記 `_html_buy_button_result` | バッチ `result(timeout=…)` のみ | 従来 `inventory_manager` | 同上 |
| `mercari_checker.py` | 277–282, 291–296 | 例外時 **`html_error` 確定**（売切にしない） | 無 | v1 系 | 維持 |
| `mercari_checker.py` | 347–348 | v2 HEAD：**404 → `deleted` 確定** | HEAD 1 回 | v2 系 | — |
| `mercari_checker.py` | 341–344, 349–352 | v2 HEAD：timeout/5xx/非200 → **`ambiguous`**（売切にしない） | 無 | v2 系 | 維持 |
| `mercari_checker.py` | 360–446 | v2 DOM：`auction` / `sold_tentative` / `active` / `ambiguous` | Playwright 例外→`ambiguous` | v2 系 | pass2 とセット |
| `mercari_checker.py` | 449–458 | `mercari_oos_verdict_pass1`：`pool.result(timeout=150)` | タイムアウト時は **`futures.TimeoutError`** 等が送出されうる | v2 系 | `inventory_manager.py` 610–615 で **ログ+Slack 後に `raise`**（当該実行は異常終了） |
| `mercari_checker.py` | 496–504 | `batch_check_mercari` → `check_mercari_status` の結果を集約 | 各 URL `delay` のみ（API 再試行なし） | v1 API 経路 | `inventory_sync` 等が利用 |
| `inventory_manager.py` | 318–335 | `_apply_mercari_oos_to_ebay` → **`mark_out_of_stock`**（eBay 在庫 0 実行） | 上限 `_can_apply_oos` のみ | 在庫本流 | ガードレールは `MAX_OUT_OF_STOCK_PER_RUN` |
| `inventory_manager.py` | 352–378 | pending **pass2** で `sold_tentative` のみ **`mark_out_of_stock`** | 時間二段（pending ファイル） | v2 **二段** | Phase 0「二段検証」の実体 |
| `inventory_manager.py` | 393–420 | v2 ON：`deleted` / `auction` は **pass1 単回で即 `mark_out_of_stock`** | 無 | v2。v3/cron 別なら **併走可** | **要確認**: sold だけ二段で del/auc が一段であることの妥当性 |
| `inventory_manager.py` | 421–437 | v2：`sold_tentative` → pending（**単回では OOS しない**） | 無 | v2 | 意図どおり |
| `inventory_manager.py` | 447–532 | v2 OFF：`html_verify_urls` → API。`sold_out`/`deleted`/`auction` で **`mark_out_of_stock`**。`error`/`html_error` は **OOS しない** | 無 | 従来系 | HTML+API の整合 |
| `scripts/inventory_manager_v3.py` | 199–258 | `_classify_mercari_dom`（JS IIFE 源）：DOM 上の `deleted` / `sold` / `auction` / `active` の素地 | **`with_retry(..., retries=1)`** で `page.evaluate`（最大 2 回） | **`inventory_manager.py` と独立** | 併走時は二重 OOS リスク（運用で排他） |
| `scripts/inventory_manager_v3.py` | 261–365 | `_inspect_mercari_url`：**`playwright_goto_with_retry`**（`wait_until=load`, **attempts=2**）+ 主要 selector 待ち + 2.5s；タイムアウト/例外 → **`verdict: active`（OOS 断定しない）** | **goto 一時系のみ再試行** | v3 のみ | Phase 0「曖昧は進めない」と整合（Step 2.7 再棚: 2026-04-23） |
| `scripts/inventory_manager_v3.py` | 313–318 | URL が notfound 系 → **`deleted` verdict**（単体では `_v3_dual_confirm_oos` 前） | 無 | v3 | HEAD は二系統内 |
| `scripts/inventory_manager_v3.py` | 346–360 | DOM `empty_html` / `deleted` / `auction` / `sold` / `active` を **verdict に反映** | 上記 evaluate リトライ | v3 | `sold` は item-detail 文言依存 |
| `scripts/inventory_manager_v3.py` | 388–428 | **`_v3_dual_confirm_oos`**：DOM + API（+ `url_notfound` 時 HEAD 404）。不一致 / `error` / `html_error` → **OOS しない** | API は `item_id` ありで DOM と並走取得可（突合ロジック不変） | v3 **二系統** | — |
| `scripts/inventory_manager_v3.py` | 431–446 | `_mark_oos_v3` → **`set_quantity(0)`**（dual_ok の `sold`/`auction`/`deleted` のみ） | `set_quantity` 単発失敗はログのみ | v3 | eBay 429 は `ebay_updater` 依存 |
| `mercari_scraper.py` | 84 | クローラ本体：`page.goto(..., MERCARI_PAGE_GOTO_TIMEOUT_MS)` | 呼び出し元（例: `auto_lister`）が `MERCARI_SCRAPE_MAX_RETRIES` でリトライ | 出品・仕入系 | config で ms 統一 |
| `mercari_scraper.py` | 88–93 | レート制限検出 → **`error` 相当**（`success` False、`Rate limited`） | `mercari_breaker` のみ | 出品系 | 売切断定ではない |
| `mercari_scraper.py` | 130–134 | DOM/JSON 等で売切シグナル → **`status: sold_out` 確定** | 無（1 ページ内） | 出品系 | `auto_lister` が参照 |
| `mercari_scraper.py` | 180–192 | オークション検出 → **`status` 非 active で返却**（仕入不可） | 無 | 出品系 | eBay 在庫には触れない |
| `mercari_scraper.py` | 211–215 | `require_buy_button` かつ購入 CTA なし → **`sold_out` 確定** | 無 | 出品系 | 誤検知リスクはコメント参照 |
| `mercari_scraper.py` | 343–348 | タイトル/価格取得不可 → **`sold_out` 確定**（コメントで根拠記載） | 無 | 出品系 | **要検討**: 一時障害との区別 |
| `order_monitor.py` | 186–201 | `check_mercari_status` で `sold_out`/`deleted` → **無在庫扱い** + **`mark_out_of_stock`** | `check_mercari_status` 内に専用 retry なし | **注文ジョブ**（在庫 cron と独立） | 例外時は `mercari_available=True` のまま |
| `order_monitor.py` | 231–234 | 注文ごとに **無条件で `mark_out_of_stock`**（売れた前提） | 無 | 同上 | **要確認**: 186–201 との二重呼びの意図 |
| `main.py` | 86–121 | `sold_out`/`deleted`/`auction` → **`mark_out_of_stock`**（dry-run 除く） | `check_mercari_status` の delay のみ | **旧監視 `main.py`**（`inventory_manager` と別） | cron で併走するか要確認 |
| `main.py` | 123–126 | `error` → シートにチェックエラー記録（**OOS しない**） | 無 | 同上 | 維持 |
| `overnight_run.py` | 169–179 | メルカリ `sold_out`/`deleted` → **`mark_out_of_stock`** | 無 | 夜間バッチ | cron 有無の確認 |
| `inventory_sync.py` | 47–53 | `batch_check_mercari` 結果で `sold_out`/`deleted` のみ **`mark_out_of_stock`**（`auction` は対象外） | batch の delay のみ | 手動/メンテ系 | `auction` を拾わない仕様の意図確認 |
| `repair_inventory.py` | 90–93 | `sold_out`/`deleted` → **`mark_out_of_stock`** | 無 | メンテ系 | — |
| `sheets_manager.py` | 446–448 | `purge_unbuyable_queue_rows`：`check_mercari_status` で **`sold_out`/`deleted`/`auction`** → 行削除・`record_sold` | `check_mercari_status` 単発 | 出品前パージ | Sheets 読み取りは `_retry_api_call`（429 等） |
| `auto_lister.py` | 1182–1208 | スクレイプ/API で **`sold_out`/`deleted`/`auction`** → 出品スキップ（シート更新） | スクレイプは 1153–1171 で **最大 `MERCARI_SCRAPE_MAX_RETRIES` 回** | 出品系 | 在庫 cron とは独立 |
| `auto_lister.py` | 343–356 | **Gemini** REST **429** → `sleep(15*(attempt+1))` で **最大 3 回** | **有** | AI 層（eBay Trading ではない） | 表記上「eBay API」ではない |
| `auto_sourcer.py` | 181 | `page.goto` **30000ms** | キーワード間待機のみ | リサーチ | 在庫断定ではない |
| `auto_sourcer.py` | 363–370 | `check_mercari_status` で **`auction`/`sold_out`/`deleted`** → 候補から除外（eBay OOS ではない） | API 単発 | リサーチ系 | — |
| `manual_sourcer.py` | 101 | `page.goto` **30000ms**（`domcontentloaded`） | 無 | 手動リサーチ | — |
| `ebay_updater.py` | 125–145, 161–183, 231–253, 280–319, 341–363, 386–404 | `requests.post` 単発。失敗は **`success: False`**。**HTTP 429 の文字列grep 上の専用リトライなし** | **無** | 全経路共通の eBay 書き込み | **Phase 0 候補**: Trading の rate limit |
| `ebay_updater.py` | 316 | `get_all_active_list_items`：ページ間 **`time.sleep(0.4)`** のみ | ページ失敗で `break` | Active 一覧 | 429 時の挙動は未実装 |
| `sheets_manager.py` | 36–76 | `_retry_api_call`：**429/500/503** 等 | **有**（指数バックオフ） | Google API のみ | eBay とは独立 |
| `scripts/end_oos_listings_from_csv.py` | 153–160 | `GetItem` の **qty==0 かつ listing Active** → 終了対象と断定 | `get_item_status` 単発 | 掃除系 | `--force-end-all` は別経路（危険） |
| `scripts/end_oos_listings_from_csv.py` | 93–103, 137–141 | `end_fixed_price_listing` 実行（成功/失敗はログ） | `sleep` のみ | 同上 | — |
| `scripts/repair_false_ebay_oos_vs_mercari.py` | 202–223 | `check_stock_by_purchase_button` が **`active` のときのみ** `set_quantity(1)`。非 active は **復旧せず**（HTML 判定を信頼） | `--delay` のみ | 救済系 | eBay を増やす側の断定 |

---

## VPS crontab

### SSH 接続試行（2026-04-21）

Cursor のシェルから次を実行したが、いずれも **`Permission denied (publickey,password)`** で接続できず、**`crontab -l` は取得できなかった**。

- `ssh -o BatchMode=yes root@133.117.76.193 'crontab -l'`
- `ssh -o BatchMode=yes mercari-vps 'crontab -l'`（`~/.ssh/config` で `HostName 133.117.76.193` + `IdentityFile ~/.ssh/mercari_vps`）
- `ssh -i ~/.ssh/mercari_vps -o BatchMode=yes root@133.117.76.193 'crontab -l'`

**実機の全文を本文に載せるには**、純之介の Mac 等で SSH が通る環境から `crontab -l` の出力を取得し、下記「実機 `crontab -l` 全文」ブロックへ**そのまま貼り替え**てください。

### 実機 `crontab -l` 全文

```text
（未取得 — 上記のとおり本環境から SSH 不可。取得後、このブロックを crontab -l の出力のみに置き換える。）

# Mac から取得例（鍵が通るホストエイリアスがある場合）:
# ssh -o ServerAliveInterval=60 -o StrictHostKeyChecking=accept-new mercari-vps 'crontab -l'
# エイリアスが無い場合:
# ssh -i ~/.ssh/mercari_vps -o ServerAliveInterval=60 -o StrictHostKeyChecking=accept-new root@133.117.76.193 'crontab -l'
```

### `scripts/vps.crontab.example` との差分

**実機 crontab が未取得のため、例ファイルとの差分は未確定**（実機全文を上記ブロックに貼ったあと、ここに箇条書きで追記する）。

**突合の目安（リポジトリ例に含まれる「実ジョブ行」のみ抜粋）** — 出典: `scripts/vps.crontab.example`

| # | 例のスケジュールとコマンド（要約） |
|---|-----------------------------------|
| 1 | `0 */3 * * *` … `inventory_manager.py` |
| 2 | `5 * * * *` … `order_monitor.py` |
| 3 | `0 1 * * *` … `timeout 2h` … `auto_sourcer.py --max-per-keyword 12` |
| 4 | `0 4 * * *` … `fill_daily_until_done.sh 70` |
| 5 | `*/30 * * * *` … `priority_listings_background.sh` |

**差分チェックリスト（実機取得後に埋める）**

- [ ] 上表 1〜5 の行が実機に**すべて存在**するか（欠落・コメントアウト・スケジュール変更）
- [ ] 実機に**のみ**存在する行（例: `scripts/inventory_manager_v3.py`、`supervisor.py`、`heartbeat`、`fill_daily` の件数変更、`systemd` 関連の二重起動防止など）
- [ ] 先頭の `SHELL` / `PATH` / `CRON_TZ=Asia/Tokyo` が実機にあるか
- [ ] 作業ディレクトリが `/opt/export-bot` 以外になっていないか

### 監査表（cron 由来の系統・再掲）

| ファイル | 行番号 | 確定判定内容 | retry有無 | 独立系統の有無 | 対応要否 |
|----------|--------|--------------|-----------|----------------|----------|
| `scripts/vps.crontab.example` | 17 | `inventory_manager.py`（在庫 cron） | cron のみ | **在庫本流** | 実機と突合 |
| `scripts/vps.crontab.example` | 20 | `order_monitor.py`（注文） | 同上 | **注文系**（在庫 cron と独立プロセス） | 同上 |
| `scripts/vps.crontab.example` | 25 | `auto_sourcer.py` | `timeout 2h` のみ | リサーチ | 同上 |
| `scripts/vps.crontab.example` | 29 | `fill_daily_until_done.sh` | シェル依存 | 出品 | 同上 |
| `scripts/vps.crontab.example` | 34 | `priority_listings_background.sh` | `flock` | 手動キュー | 同上 |
| `COPY_PASTE_SETUP.txt` | 292–293 | **任意** `scripts/inventory_manager_v3.py` の cron 例（既存在庫行と**別プロセス**） | 別ロック（文面参照） | **v3 は `inventory_manager.py` と独立系統になりうる** | 実機 crontab に有無を記載 |

---

## 純之介への確認事項

1. **実 VPS の `crontab -l` 全文**を本文「実機 `crontab -l` 全文」に貼り、`scripts/vps.crontab.example` との差分を「差分」節に追記（本環境は SSH 未認証のため未取得）。  
2. **`inventory_manager.py` と `inventory_manager_v3.py` の同時稼働**の有無と、二重 OOS / Slack の許容。  
3. **v2 で `deleted`/`auction` が pass1 一段で `mark_out_of_stock`** になる仕様の継続可否。  
4. ~~`order_monitor.py` の `mark_out_of_stock` 二重呼び~~ → **Step 2 で 1 回に統合済み**（コミット履歴参照）。  
5. **`ebay_updater.py` に Trading API 用 429 リトライ**を入れるか（Phase 0 は停止のみ。Phase 0.5 で指数バックオフ検討）。

---

## Step 2.7 — 再棚卸し（Stage G 前）

段階デプロイ **Stage F 異常なし** のあと、コードと本番ログを突き合わせて更新する。

### 実施記録（2026-04-23）

- [x] `mercari_checker.py` / `mercari_scraper.py` / `auto_sourcer.py` / `scripts/inventory_manager_v3.py` / `ebay_updater.py` / `auto_lister.py` / `order_monitor.py` / `heartbeat.py` の Phase 0 変更が意図どおりか（**v3** は `phase0-perf` を `2026-04-04-mq2r` に merge 済み。性能・二系統・リトライは [PHASE_0_PERF_ANALYSIS.md](./PHASE_0_PERF_ANALYSIS.md) §2–§4・§8 参照）  
- [x] **タイムアウト・429・二系統不一致**時に「売切/OOS」と断定していないこと — **dry-run 108 件**でタイムアウト 0・二系統不一致 0・誤 OOS 0（実測は §8）。本番ログは cron 再有効化後に別途確認。  
- [ ] 実機 `crontab -l` に **v3** と **heartbeat `*/15`** が並存しているか — **本タスク範囲外**（純之介が cron 再有効化を別途判断）。未取得の VPS 節は従来どおり。

### grep 再確認（Phase 0 ガード違反パターンの混入なし）

実施ディレクトリ: `海外輸出ボット/`（`japan-export-bot/` はミラー扱いで本監査の正本から除外）。

1. **確定判定に絡む `page.goto` の直叩き**（`phase0_guards` 外）  
   - `rg 'page\\.goto\\(' --glob '*.py'` → 本番ツリーでは **`utils/phase0_guards.py`**（`playwright_goto_with_retry` 内）および **`manual_sourcer.py`**（手動リサーチ）のみ。在庫 v3 / `mercari_checker` / `mercari_scraper` は **`playwright_goto_with_retry(..., attempts=2)`** 経由。  
2. **`playwright_goto_with_retry` の `attempts`**  
   - `rg 'playwright_goto_with_retry\\(' --glob '*.py'` の呼び出しはすべて **`attempts=2` 明示、または省略（既定 2）** — **リトライ無し化なし**。  
3. **v3 二系統**  
   - `_v3_dual_confirm_oos` が `scripts/inventory_manager_v3.py` に残存し、`set_quantity(0)` は dual_ok 後のみ。  
4. **参考（Stage G 文書どおり）**

```bash
cd "/Users/miyazakijunnosuke/Downloads/eBay/海外輸出ボット"
rg "requests\.post\(" ebay_updater.py
rg -n "mark_out_of_stock" order_monitor.py
```

**結論**: 新規の「goto 直叩きで確定」「リトライ削除」「二系統突合スキップ」パターンは **検出されず**。監査表の v3 行は上表（`scripts/inventory_manager_v3.py` 5 行）に **2026-04-23 時点のソース**で更新済み。

---

## Phase 0 完了（二者確認・Stage G）

**1 サイクル監視異常なし**ののち、次を実施してから本ファイルを **`PHASE_0_COMPLETED.md`** にリネームする。

**運用（2026-04-23）**: 以下に **確認者1** を記録した時点では本ファイル名は **`PHASE_0_AUDIT.md` のまま**とする。**確認者2（純之介）の最終承認**および Stage G 完了判断のあと、リネームする。

| 役割 | 氏名 | 日付 | 署名 |
|------|------|------|------|
| 実装・デプロイ確認 | Claude Code（Cursor Agent） | 2026-04-23 | Step 2.7 grep 実施。実測: **v3 dry-run 108 件を約 13 分で完走**、誤 OOS・タイムアウト・二系統不一致は **いずれも 0**（詳細 [PHASE_0_PERF_ANALYSIS.md](./PHASE_0_PERF_ANALYSIS.md) §8）。`merge(phase0-perf)` を `2026-04-04-mq2r` に反映済み。本番 deploy・cron 再有効化は未実施（純之介判断）。 |
| 承認（オーナー） | 純之介 | （最終承認待ち） | 次回コミュニケーションで承認・日付・署名を記入のうえ **`PHASE_0_COMPLETED.md` へリネーム**する。 |

---

## 参照

- [PHASE_0_CHECKLIST.md](./PHASE_0_CHECKLIST.md)
- [PHASE_0_DEPLOY_STAGED.md](./PHASE_0_DEPLOY_STAGED.md)
- [PHASE_0_STAGING.md](./PHASE_0_STAGING.md)
- [PHASE_0_DEFERRED.md](./PHASE_0_DEFERRED.md)
- [JAPAN_EXPORT_MODEL_REFRESH_v1.md](./JAPAN_EXPORT_MODEL_REFRESH_v1.md)
