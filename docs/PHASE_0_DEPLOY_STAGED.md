# Phase 0 — 本番段階デプロイ（ステージングなし）

**前提:** 別 Sandbox / 別スプレッドシートのステージングは未構築。本番 VPS で **段階的に** 検証する。  
**正本のコピペ:** 作業場所は **`[Mac]`** / **`[VPS]`** を見てターミナルに貼る。

---

## Stage A: v3 を一時停止（安全確保）

**[VPS]**（`ssh root@133.117.76.193` 済みのシェル）

```bash
crontab -e
```

- `inventory_manager_v3.py` の行（例: `0 */3 * * * ... scripts/inventory_manager_v3.py`）の**先頭に `#`** を付けてコメントアウトする。
- 保存後、次で v3 が止まっていることを確認する。

```bash
crontab -l | grep -E 'inventory_manager_v3|#' || true
```

---

## Stage B: コード反映

**[Mac]**

```bash
cd "/Users/miyazakijunnosuke/Downloads/eBay/海外輸出ボット"
VPS_IP=133.117.76.193 bash deploy.sh
```

**[VPS]**

```bash
ssh root@133.117.76.193
cd /opt/export-bot && ./venv/bin/pip install -r requirements.txt
```

---

## Stage C: v3 単体動作確認（cron に載せる前）

**[VPS]**

```bash
cd /opt/export-bot && ./venv/bin/python3 -u scripts/inventory_manager_v3.py
```

**確認項目**

- タイムアウト時は OOS に進まず **active 維持**になっているログがあること  
- **二系統一致**のときのみ `set_quantity(0)` / OOS ログがあること  
- Slack に **Phase0 メトリクス**（タイムアウト件数・二系統不一致件数）が載ること  
- `logs/v3_heartbeat_state.json` が生成されること  

---

## Stage D: heartbeat 単体動作確認

**[VPS]**

```bash
cd /opt/export-bot && ./venv/bin/python3 -u heartbeat.py
```

- ログまたはシート `自動出品!H1` に、v3 状態 / Sheets / Slack の要約が出ること。

---

## Stage E: cron 再登録

**[VPS]**

```bash
crontab -e
```

1. **v3** 行の `#` を外して有効化する。  
2. **heartbeat** を次の 1 行追加する（例: 15 分毎）。

```text
*/15 * * * * cd /opt/export-bot && ./venv/bin/python3 -u heartbeat.py >> logs/cron_heartbeat.log 2>&1
```

保存後:

```bash
crontab -l
```

---

## Stage F: 1 サイクル監視（約 3 時間）

- v3 が **0,3,6,… 時台**に起動している（ログ・Slack）  
- タイムアウト時に **誤 OOS していない**  
- heartbeat が **15 分毎**に記録されている  
- Slack に **想定外のエラー連投がない**  
- **誤 OOS** が発生していない  

異常時は **即ロールバック**（下記）。問題なければ **Stage G** へ。

---

## Stage G: 完了記録（1 サイクル異常なしのあと）

**2026-04-23**: リポジトリ（Mac / Cursor）で手順 1〜4 を実施し、正本は **[PHASE_0_COMPLETED.md](./PHASE_0_COMPLETED.md)**（旧 `docs/PHASE_0_AUDIT.md` を `git mv`）に集約済み。

作業時のチェックリスト（完了後の参照用）:

1. **Step 2.7（再棚卸し）** — 監査表の更新（[PHASE_0_COMPLETED.md](./PHASE_0_COMPLETED.md)）  
2. 下記 **grep 参考** で明らかな退行がないことを確認する（ゼロ保証の厳密証明ではない）。  
3. **二者確認** — 純之介の最終承認（同上ファイル）  
4. **`PHASE_0_COMPLETED.md` へのリネーム** — `git mv` 済み  
5. `docs/PHASE_0_STAGING.md` に「ステージングなし段階デプロイ実施済み」等を追記する（オーナー判断）  
6. `git commit` & `git push`（push はオーナーの Mac から）  

### Step 2.7 用 grep 参考（Mac、リポジトリルート）

```bash
cd "/Users/miyazakijunnosuke/Downloads/eBay/海外輸出ボット"
# eBay Trading: 直接 requests.post が残っていない（ebay_updater は trading_post 経由）
rg "requests\.post\(" ebay_updater.py
# order_monitor: mark_out_of_stock の重複呼び出しがない（1 ブロック想定）
rg -n "mark_out_of_stock" order_monitor.py
```

---

## ロールバック（問題発生時・即）

**[VPS]**

```bash
ssh root@133.117.76.193
cd /opt/export-bot
git log --oneline -5
git reset --hard <前の安定コミットのハッシュ>
./venv/bin/pip install -r requirements.txt
crontab -e
```

- **heartbeat** 行を削除またはコメントアウト  
- 必要なら **v3** 行もコメントアウト  

---

## 関連

- [PHASE_0_STAGING.md](./PHASE_0_STAGING.md) — ステージング欄 + 本手順の索引  
- [PHASE_0_DEFERRED.md](./PHASE_0_DEFERRED.md) — Phase 0.5 / Phase 1 持ち越し  
- [PHASE_0_COMPLETED.md](./PHASE_0_COMPLETED.md) — Step 1 棚卸し・Step 2.7・二者確認の完了記録（2026-04-23）
