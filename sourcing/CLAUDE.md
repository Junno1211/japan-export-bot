# JAPAN EXPORT - ソーシング共通ルール

## 利益計算式
```
利益(USD) = 販売価格(USD) × 0.804 − (メルカリ価格 ÷ 1.1 ÷ 155) − (3,000 ÷ 155)
```

- 手数料合計: 19.6%（FVF 13.25% + 海外 1.35% + Payoneer 2% + Promoted 3%）
- 為替レート: 155 JPY/USD
- 消費税還付: 仕入れ価格の10%
- 送料固定費: ¥3,000（FedEx等、毎回必ず差し引くこと）

## 仕入れ判断基準
- 最低利益: ¥3,000（送料控除後）
- ROI目標: 25%以上
- eBay実売実績: 直近90日で3件以上
- 仕入れ上限: ¥250,000/品

## 出品ルール
- 必ず「SHIPPING WORLDWIDE」
- 出品数目標: 80件/日
- Promoted Listings: 3%

## NG共通ルール
- ノーマルシングル（レアリティ低）
- ¥1,000以下の商品
- DAIVE推奨品
- ジャンク / 訳あり / 故障 / 部品取り

## ソーシングフロー
```
1. 各部署のキーワードで eBay Sold を検索（get_winning_titles）
2. 成約速度・相場価格を取得（get_sold_velocity / get_market_price）
3. メルカリで仕入れ候補を検索（mercari_scraper）
4. 利益計算（calc_profit） → ROI 25%以上 & 利益¥3,000以上をフィルタ
5. 自動出品シートに追加（append_to_auto_sheet）
```

## 使用ツール
- `auto_sourcer.py` - 自動リサーチ（検索キーワードシートから実行）
- `manual_sourcer.py` - 手動URL投入リサーチ
- `mercari_scraper.py` - メルカリスクレイピング
- `ebay_price_checker.py` - eBay相場・Sold実績チェック

## 部署別キーワード設定
各部署の `keywords.json` に検索キーワードを定義。
`auto_sourcer.py` が全部署のキーワードを順に処理する。

## レポート先
CEO（週次）、出品部（随時）
