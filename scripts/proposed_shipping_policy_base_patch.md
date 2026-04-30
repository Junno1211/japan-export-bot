# `_SHIPPING_POLICY_BASE` 更新案（人手レビュー用・自動適用禁止）

このファイルは **config.py を置き換えない**。純之介が `dump_shipping_policies.py` の TSV と  
`validate_shipping_policy_map.py` の結果を見て、誤った Profile ID が混ざらないよう **手動で**  
`config.py` の `_SHIPPING_POLICY_BASE` を編集するためのチェックリスト兼 diff 雛形です。

## 命名規則（リポジトリ根拠）

Seller Hub のポリシー**表示名**は、`shipping_policy_select.policy_label_for_bracket` と一致させること。

- `bracket_key == 0` → 例: `$0–$99`（0–99.99 USD）
- `bracket_key == 100` → 例: `$100–$149`
- 以降 $50 刻み。正規表現によるパースは `shipping_policy_select.parse_band_from_policy_name`  
  （en dash `–` / hyphen `-` / カンマ付き金額に対応）

`test_rules.py` の `test_shipping_band_parse_and_mismatch` も同じパーサを前提にしています。

## 作業順序（本命）

1. **Seller Hub**（Business policies / Shipping）で、各価格帯に **別々の** Fulfillment ポリシーを用意する。  
   表示名は上記と **一字一句揃えない** 場合は、`validate` で ERROR になるので `policy_label_for_bracket` に合わせてリネームする。
2. Mac で TSV を取得:  
   `python3 scripts/dump_shipping_policies.py > /tmp/policies.tsv`  
   （`.env` の認証情報を読む。トークン文字列をチャット・スクリーンショットに貼らない。）
3. 検証:  
   `python3 scripts/validate_shipping_policy_map.py /tmp/policies.tsv`  
   ERROR が 0 になるまで `_SHIPPING_POLICY_BASE` を調整する（調整は **config 手編集**）。
4. 下の diff 雛形に、TSV の **数字 ID だけ** を転記し、Git / PR で差分レビューしてから本番反映。

## 前方埋めについて

`_build_shipping_policy_map()` の前方埋めは **変更しない**（フェイルセーフ）。  
本命で `_SHIPPING_POLICY_BASE` の各「節」に正しい ID を入れれば、同一 ID の共有 WARNING は消える。

## diff 雛形（プレースホルダ — 実 ID は TSV から手貼り）

```diff
--- a/config.py
+++ b/config.py
@@ -189,6 +189,19 @@ LISTING_MAX_PRICE_USD = 2499.0
 
 _SHIPPING_POLICY_BASE = {
-    0:    "279942900015",
-    100:  "279802312015",
-    # ... 以下、dump TSV の name が policy_label_for_bracket(key) と一致する行の ID を貼る
+    0:    "__REPLACE_WITH_TSV_ID_FOR_$0–$99__",
+    100:  "__REPLACE_WITH_TSV_ID_FOR_$100–$149__",
+    150:  "__REPLACE_WITH_TSV_ID_FOR_$150–$199__",
+    200:  "__REPLACE_WITH_TSV_ID_FOR_$200–$249__",
+    250:  "__REPLACE_WITH_TSV_ID_FOR_$250–$299__",
+    300:  "__REPLACE_WITH_TSV_ID_FOR_$300–$349__",
+    350:  "__REPLACE_WITH_TSV_ID_FOR_$350–$399__",
+    500:  "__REPLACE_WITH_TSV_ID_FOR_$500–$549__",
+    550:  "__REPLACE_WITH_TSV_ID_FOR_$550–$599__",
+    650:  "__REPLACE_WITH_TSV_ID_FOR_$650–$699__",
+    700:  "__REPLACE_WITH_TSV_ID_FOR_$700–$749__",
+    1200: "__REPLACE_WITH_TSV_ID_FOR_$1200–$1249__",
+    1450: "__REPLACE_WITH_TSV_ID_FOR_$1450–$1499__",
 }
```

**注意**: 実運用では `LISTING_MAX_PRICE_USD` まで **全 bracket_key** が `SHIPPING_POLICY_MAP` に埋まる必要があります。  
現在の `_SHIPPING_POLICY_BASE` にキーが飛び飛びなのは前提どおりで、不足分は前方埋めが埋めますが、  
**共有 WARNING を消す**には、飛び先のキー（例: 400, 450, …）を `_SHIPPING_POLICY_BASE` に **明示追加**し、  
それぞれ別 Profile ID を割り当てるのが安全です（追加後も `validate` で duplicate 0 を確認）。

## 自動書き換え禁止の理由

4月の事故実績あり。Profile ID の取り違えは出品・送料表示に直結するため、**必ず人間が diff を確認**する。
