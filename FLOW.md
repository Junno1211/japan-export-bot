## 全体フロー（見栄え用まとめ）

このプロジェクトは大きく「リサーチ → 出品 → 同期（在庫/価格）→ 受注通知」で回ります。

```mermaid
flowchart TD
  subgraph A[リサーチ（仕入れ候補作成）]
    K[Google Sheets: 検索キーワード] -->|キーワード取得| AS[auto_sourcer.py]
    AS -->|eBay: 相場/売れ行き参照| EP[ebay_price_checker.py]
    AS -->|Mercari検索スクレイプ| MS[Playwright]
    AS -->|採算OKのみ追記| SH1[Google Sheets: 自動出品]
  end

  subgraph B[出品（自動）]
    SH2[Google Sheets: 優先出品/自動出品] -->|URL + 期待利益| AL[auto_lister.py]
    AL -->|Mercari商品スクレイプ| MI[mercari_scraper.py]
    AL -->|Geminiで最適化| GM[Gemini API]
    AL -->|eBayに出品| EB1[eBay Trading API: AddFixedPriceItem]
    AL -->|ItemID等を反映| INV[Google Sheets: 在庫管理表]
  end

  subgraph C[同期（在庫監視→eBay終了）]
    INV -->|Active行を取得| M[main.py / inventory_sync.py]
    M -->|Mercari在庫確認| MC[mercari_scraper.py / mercari_checker.py]
    M -->|売り切れ/削除| EB0[eBay Trading API: Quantity=0]
    M -->|シート更新/削除| INV
  end

  subgraph D[受注（緊急仕入れ通知）]
    O[order_monitor.py] -->|GetOrders| EB2[eBay Trading API: GetOrders]
    O -->|仕入れ発生を通知| SL[Slack]
    O -->|二重通知防止| PO[processed_orders.json]
  end

  SH1 --> SH2
  INV --> D
```

## 「普段どれを回す？」（最小）
- **自動で在庫監視（停止防止が最優先）**: `main.py`（cronで定期実行）
- **自動で仕入れ候補作成**: `auto_sourcer.py`（必要なら定期実行）
- **自動で出品**: `auto_lister.py`（優先出品→自動出品の順に処理）
- **売れたら通知**: `order_monitor.py`（定期実行 or 常駐運用）

