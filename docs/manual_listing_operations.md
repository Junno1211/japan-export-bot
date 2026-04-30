# 手動キュー（スプレッドシート「手動」タブ）の運用

## 本番方針（cron）

- **推奨**: 手動タブのバックグラウンド処理は **有効な 1 行だけ** を crontab に入れる。
- 正本の例は `scripts/vps.crontab.example` の「手動キュー」セクション（30 分毎の `priority_listings_background.sh`）。
- **意図的に止める** 場合は、その 1 行を **コメントアウト** するか削除する。`# DISABLED ...` と **有効行が混在** しないようにする（どちらが効いているか不明になるため）。

## 手動で 1 回まわす（PC なし / メンテ時）

VPS 上で（ユーザー環境の IP・パスに合わせて実行）:

```bash
cd /opt/export-bot && bash scripts/priority_listings_background.sh
```

ログ確認:

```bash
ls -t /opt/export-bot/logs/bg_priority_listings_all_*.log | head -1 | xargs tail -f
```

## cron を止めたあと再開する手順

1. `crontab -e` で、手動キュー行の先頭 `#` を外す **または** `scripts/vps.crontab.example` から該当 1 行をコピーする。
2. **重複行がない** ことを確認（同じ `priority_listings_background.sh` が複数時刻に走らないようにする）。
3. 以前付けた `# DISABLED 2026-...` の説明コメントだけが残り、実パスがコメントアウトされたまま、という状態を解消する。

## 関連ファイル

- `scripts/priority_listings_background.sh` — `flock` による重複起動抑止
- `scripts/vps.crontab.example` — JST・在庫 cron とあわせた記載例
- `auto_lister.py` — `PRIORITY_SHEET_NAME`（既定「手動」）の処理

## Shipping policy（本命: band ごとの Profile ID）

手順の詳細は README の「本命: band ごとに Seller Hub の Profile ID を作り込む」を正とする。要点のみ:

1. Seller Hub で **Fulfillment / Shipping** ポリシーを価格帯ごとに分ける（表示名は `policy_label_for_bracket` と一致）。
2. Mac: `python3 scripts/dump_shipping_policies.py > policies.tsv`（トークン・秘密は貼らない）。
3. `python3 scripts/validate_shipping_policy_map.py policies.tsv` で ERROR をゼロにする。
4. `scripts/proposed_shipping_policy_base_patch.md` を見て **config.py を手動編集**（自動書き換え禁止）。
5. `scp` で `config.py` 等を VPS `/opt/export-bot/` へ。
