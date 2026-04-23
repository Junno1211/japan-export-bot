# Phase 0 — ステージング環境（Step 2.1 記録）

最終更新: 2026-04-21（Cursor エージェントがリポジトリ方針に基づき雛形作成。**純之介が実環境を確認して埋めること。**）

## ステージング環境なしでの段階デプロイ

別 Sandbox / 別シートのステージングは **未構築** のため、本番では **v3 一時停止 → deploy → 手動検証 → heartbeat / v3 の cron 再開 → 1 サイクル監視** の順で進める。

| 項目 | 状態 |
|------|------|
| 手順書 | **[PHASE_0_DEPLOY_STAGED.md](./PHASE_0_DEPLOY_STAGED.md)**（Stage A〜G・ロールバック） |
| 実施日 / 実施者 | **未記入**（Stage G 完了時に記入） |
| 1 サイクル監視結果 | **未記入**（異常なしで Stage G へ） |

持ち越し項目は **[PHASE_0_DEFERRED.md](./PHASE_0_DEFERRED.md)**。

## 方針

- ステージングが **未構築** のとき、本番 VPS への直接適用はリスクが高いため、**コードはリポジトリにマージしても** 本番反映は `COPY_PASTE_SETUP.txt` の手順に従い、**検証後に deploy** とする。
- 上記のとおり、可能な範囲では **[PHASE_0_DEPLOY_STAGED.md](./PHASE_0_DEPLOY_STAGED.md)** の **段階デプロイ** を優先する。
- ロールバックは **git revert / 旧コミットの deploy** と **VPS `.env` の feature flag** の二本立てを推奨する。

## 別 eBay アプリ（Sandbox）の有無

| 項目 | 状態 |
|------|------|
| Sandbox アプリ ID / トークン | **未記入**（純之介確認） |
| 本番 `EBAY_ENV` と切り替え手順 | **未記入** |

## 別 Google スプレッドシート（検証用）の有無

| 項目 | 状態 |
|------|------|
| 検証用 `SPREADSHEET_ID` | **未記入** |
| 本番シートとの切替方法 | **未記入** |

## Feature flag / ロールバック経路

| フラグ / 手段 | 用途 |
|---------------|------|
| `INVENTORY_APPLY_EBAY_OOS` | 在庫 OOS の eBay 反映を止める（既存 `.env`） |
| `INVENTORY_MERCARI_OOS_V2` | 在庫 v1/v2 切替（config / .env） |
| `scripts/inventory_manager_v3.py` の cron 削除 | v3 在庫ジョブのみ停止 |
| `git revert` + `deploy.sh` | コードロールバック |

## メモ

- Phase 0 Step 2 の実装は **本番 API 互換**のままガードを追加している。Sandbox 未整備でも **429 時は処理停止 + Slack** により誤確定より安全側に倒す。

## 関連（完了記録）

- [PHASE_0_COMPLETED.md](./PHASE_0_COMPLETED.md) — Phase 0 棚卸し・再棚・二者確認の正本（旧 `PHASE_0_AUDIT.md` を 2026-04-23 に `git mv`）
