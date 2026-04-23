# Phase 0 在庫 v3 性能分析（2026-04-23）

対象: `scripts/inventory_manager_v3.py` と `utils/phase0_guards.py` / `mercari_checker.py` の Phase 0 関連実装。  
背景: 2026-04-22 深夜の本番試行で 111 件が約 25 分でほぼ進まず、実用外のペースだった事象の整理と改善方針。

---

## 1. 事象サマリ（観測）

| 項目 | 内容 |
|------|------|
| スクリプト | `inventory_manager_v3`（Playwright + 二系統 OOS 確定） |
| 件数 | 111 件規模 |
| CPU | Python ほぼ待機、Chromium 低負荷 |
| プロファイル | `/tmp/playwright_chromiumdev_profile-*` が作成直後で停滞気味 |

**解釈**: メインスレッドが **I/O 待ち（ナビゲーション完了待ち・固定 sleep）** に支配されていた可能性が高い。

---

## 2. ボトルネック特定（コード根拠）

### 2.1 最大要因: `networkidle` + 長い `goto` 下限 + 固定 10 秒待機（改善前）

`_inspect_mercari_url`（旧実装）:

- `page.goto(..., wait_until="networkidle", timeout=goto_ms)`  
  `goto_ms = max(180_000, MERCARI_PAGE_GOTO_TIMEOUT_MS)` → **最低 180 秒**のナビゲーション上限。
- メルカリ商品 SPA はバックグラウンド通信が続きやすく、`networkidle` は **完了が遅い・稀に極端に遅い**。
- 成功後に **`wait_for_timeout(10_000)` 相当の 10 秒固定**で描画安定を取っていた。

**1 件あたりのオーダー感（旧）**:

- 典型: `networkidle` 待ち（数十秒〜） + **10 s** + `playwright_goto_with_retry`（最大 2 回）の瞬間系リトライ sleep（最大 1+2 秒程度） + ループ末 `sleep(0.25)`。
- 最悪: タイムアウト × 2 試行（180s×2）に近い挙動も理論上あり得る。

→ 111 件で **1〜2 時間規模**の見積もりと整合する。

### 2.2 `phase0_guards.playwright_goto_with_retry`

| パラメータ | 値（既定） |
|------------|------------|
| `attempts` | v3 では **2**（= 最大 2 回 `goto`） |
| 再試行条件 | タイムアウト / navigation / `net::` 等の **一時エラーのみ** |
| `sleep_between` | 既定 **1.0s** × 試行番号（1 回目リトライで約 1s） |

**Phase 0 制約**: リトライ **ゼロ化は不可**。改善後も **最低 1 回の再試行相当**（`attempts=2`）を維持。

### 2.3 `phase0_guards.with_retry`（DOM `evaluate`）

| パラメータ | v3 での値 |
|------------|-----------|
| `retries` | **1**（合計 2 回まで） |
| `backoff` | **0.5**（線形: 0.5s sleep） |

DOM 評価は軽量。ここはボトルネックの主因ではない。

### 2.4 二段階検証（DOM + API）

`_v3_dual_confirm_oos`:

- OOS 候補（`sold` / `auction` / `deleted`）のときのみ `check_mercari_status`（または同等の API スナップショット）で突合。
- **改善前**: DOM（Playwright）完了 **後に** API を直列実行 → OOS 件では DOM 時間に API 時間が **足し算**。

`check_mercari_status`（`mercari_checker.py`）:

- 先頭 `time.sleep(delay)`（v3 経路では **0.2s**）。
- `requests` の API タイムアウト **15s**（`_mercari_api_item_snapshot_no_html` も同様）。

**改善後**: `item_id` が取れる URL では、DOM 取得と **同一 item の API をスレッド上で先行開始**し、OOS 確定時は **先行結果を再利用**（Shops 等 `item_id` なしは従来どおり `check_mercari_status`）。二系統の **独立性・突合ロジックは不変**。

### 2.5 その他の累積待ち

- ループ末尾 `time.sleep(0.25)` → 111 件で **約 28 秒**（旧）。改善後 **0.12s** に短縮（429 回避用の微小間隔は維持）。
- `HEAD`（`deleted` + `url_notfound` の第 2 系統）: `timeout=15`。**件数は該当時のみ**。

### 2.6 ブラウザ再利用

v3 は **既に** `sync_playwright` 1 回・`chromium.launch` 1 回・**同一 `page` で全件巡回**（改善前から毎商品でブラウザ起動はしていない）。

---

## 3. 仮説との対応表

| 仮説 | 結論 |
|------|------|
| retry 回数過多 | `goto` 2 回 / `evaluate` 2 回は Phase 0 最小ライン。**主因ではない**（ただし `sleep_between` は短縮余地あり）。 |
| `Page.goto` タイムアウト過大 | **該当**。`max(180000, …)` と `networkidle` の組合せが支配的。 |
| 毎商品 API+DOM フル | Active では API は **OOS 候補のみ必須**。ただし **並列化で壁時計を圧縮**可能。 |
| Mercari の sleep | v3 本体は **0.25s/件**が主。`check_mercari_status` の 0.2s は二系統時のみ。 |
| Playwright 毎回起動 | **該当せず**（既に再利用）。 |

---

## 4. 改善パッチ概要（ブランチ `phase0-perf`）

| 変更 | 安全性 |
|------|--------|
| `wait_until`: `networkidle` → **`load`** | 描画前に OOS 確定しないよう、`wait_for_selector`（主要 UI）+ **2.5s** の短い安定待ちを追加。 |
| `goto_ms`: **55s〜120s**（config を挟み、180s 下限を廃止） | 遅いページはタイムアウト→**従来どおり Active 側インディテミネート**（誤 OOS に寄せない）。 |
| `playwright_goto_with_retry(..., sleep_between=0.5)` | 一時障害時の待ちのみ短縮。 |
| API **先行 submit** + OOS 時は `api_snap` 利用、Active 時は **`Future.cancel()` または drain** | 二系統の定義・不一致時の見送りは変更なし。 |
| ループ末 sleep **0.25 → 0.12** | 軽微な間隔維持。 |

**やらないこと（制約遵守）**:

- リトライ無し化、`二系統突合の削除`、曖昧状態での確定、4/1 型誤判定を招く緩和 — **すべて禁止のまま**。

---

## 5. 処理時間の推定比較（111 件・販売中が大半のモデル）

前提はいずれも **429 なし・タイムアウト稀**の「通常負荷」モデル。実測はネットワーク・メルカリ側で変動。

| 版 | 1 件あたり目安（典型 Active） | 111 件の目安 |
|----|-------------------------------|---------------|
| **改善前** | `networkidle` 20〜90s + 固定 10s + α ≒ **30〜100s+** | **約 55〜185 分**（分散大） |
| **改善後** | `load` + selector≤12s + 2.5s + α ≒ **8〜25s** | **約 15〜46 分** |

**OOS 候補が少ない**場合、API 先行は **キャンセルまたは短い drain** に抑えられ、上記の下限側に寄りやすい。  
**目標 30 分以内**は、従来比で十分現実的だが、メルカリ遅延・タイムアウト多発時は **`MERCARI_PAGE_GOTO_TIMEOUT_MS` の調整**（例: 60000〜90000）と運用監視（Slack メトリクス）で担保するのが安全。

---

## 6. 純之介レビュー用チェックリスト

- [ ] dry-run（`--limit 20` など）でログ・Slack に異常がないか  
- [ ] `active_timeout` / `active_dual_reject` の件数が従来比で異常増していないか  
- [ ] 問題なければ `2026-04-04-mq2r` への merge は **別途判断**（本ブランチに直接 merge しない方針）

---

## 7. 参照ファイル

- `scripts/inventory_manager_v3.py` — v3 メイン・DOM・二系統
- `utils/phase0_guards.py` — `with_retry` / `playwright_goto_with_retry`
- `mercari_checker.py` — `_mercari_api_item_snapshot_no_html` / `check_mercari_status`
- `tests/test_phase0_guards.py` / `tests/test_phase0_sourcing.py`
