# Phase 0 スコープ外・持ち越し（レビュー用）

**Phase 1 着手前**に以下を読み、必要なら Phase 0.5 / Phase 1 のチケットに落とす。

---

## コード（Step 2 で未改修）

| 対象 | 理由 | 推奨フェーズ |
|------|------|----------------|
| `inventory_manager.py`（v2 本流） | 運用上 **[STOPPED]** のため緊急度が v3 より低い。別途 v2 パスにも Phase 0 ガードを揃えるか要判断。 | Phase 0.5 または Phase 1 |
| `ebay_lister.py` | 本番出品の主経路は `auto_lister.py` の `add_item_to_ebay`（`ebay_updater.trading_post` 利用）。`ebay_lister.add_item` は併用状況を確認のうえガードを検討。 | Phase 1 |
| `manual_sourcer.py` | 手動実行。自動在庫パイプラインの誤判定リスクは相対的に低い。 | Phase 1（任意） |

---

## 運用

- **ステージング環境なし**での本番段階デプロイは [PHASE_0_DEPLOY_STAGED.md](./PHASE_0_DEPLOY_STAGED.md) に手順化済み。  
- **実機 `crontab -l` 全文**は [PHASE_0_COMPLETED.md](./PHASE_0_COMPLETED.md) の VPS 節に追記し、例ファイルと突合すること。

---

## メモ

- Phase 0 完了の **厳密な「違反ゼロ」**は grep だけでは証明できない。**Stage F のログ・Slack・eBay 在庫**とセットで判断する。
