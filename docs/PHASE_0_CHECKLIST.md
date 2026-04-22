# Phase 0 チェックリスト（着手条件）

[事業モデル刷新仕様書 v1.0](./JAPAN_EXPORT_MODEL_REFRESH_v1.md) の **Phase 0** を完了したことを示すためのチェックリストである。  
**Phase 0 未完了のまま Phase 1 以降に着手しない。**

---

## 1. Mercari / Playwright タイムアウトの解消

- [ ] VPS 上で `page.goto` 等のタイムアウト（例: `30000ms exceeded`）が、**許容レベル**まで減少したことをログで確認した
- [ ] タイムアウト発生時の挙動が **「曖昧な成功/失敗と断定しない」** 方針と整合している（安全側に倒す）
- [ ] 必要に応じて `MERCARI_PAGE_GOTO_TIMEOUT_MS`、プロキシ、並列数、**inventory_manager_v3** 等の待機・ナビゲーション方針が文書化されている

---

## 2. retry + 二段階検証

- [ ] メルカリ在庫・販売可否の判定で **retry**（回数・バックオフ）が定義されている
- [ ] **二段階検証**（単発では OOS/在庫確定に使わない等）が、対象ジョブで一貫して適用されている  
  - 既存: `INVENTORY_MERCARI_OOS_V2` + pending + pass2 等の有無を確認
- [ ] 「1回の失敗＝売切/在庫あり」と**断定しない**コードパスがレビュー済み

---

## 3. 環境要因による判定汚染の防止

- [ ] User-Agent / ビューポート / ヘッダ等、**本番と検証で同じ前提**が明示されている
- [ ] `navigator.webdriver` 等、ボット検知まわりの対策方針が必要なジョブで検討・適用されている
- [ ] ネットワーク・5xx・429 時は **hold / スキップ** がデフォルトである（進めてよい場合のみ進む）

---

## 4. 運用・監視

- [ ] 在庫・OOS 系ジョブの **Slack / ログ** で異常件数が追える
- [ ] 「OOS 一括大量」「API rate limit 枯渇」に相当する **ガードレール閾値**が運用側で議論・文書化されている（仕様書 Guardrail と整合）

---

## 5. 承認・証跡

- [ ] 上記 1〜4 を **純之介（または指定オーナー）が承認**した記録（日付・コミット・ログ抜粋のいずれか）がある
- [ ] Phase 1 のキックオフ条件として本チェックリストを **完了** とみなす合意がある

---

## 参照（リポジトリ内）

- [PHASE_0_AUDIT.md](./PHASE_0_AUDIT.md)（Step 1 棚卸し・Step 2.7 再棚）
- [PHASE_0_DEPLOY_STAGED.md](./PHASE_0_DEPLOY_STAGED.md)（本番段階デプロイ Stage A〜G）
- [PHASE_0_STAGING.md](./PHASE_0_STAGING.md) / [PHASE_0_DEFERRED.md](./PHASE_0_DEFERRED.md)
- `mercari_checker.py`（v2 HEAD + DOM + pending 等）
- `inventory_manager.py` / `scripts/inventory_manager_v3.py`
- `COPY_PASTE_SETUP.txt`（cron・デプロイ）
- `CLAUDE.md`（絶対ルール）
