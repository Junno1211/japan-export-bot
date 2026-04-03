# 出品部 - eBayリスティング & 最適化

## ミッション
仕入れた商品を最速・最高品質でeBayに出品し、売上を最大化する。

## 担当業務
1. **リスティング作成** - タイトル・説明文・画像・価格設定
2. **SEO最適化** - キーワード選定、タイトル80文字フル活用
3. **価格調整** - 競合価格に基づく動的価格更新
4. **一括出品** - バッチ処理による大量出品
5. **品質管理** - リスティングエラーの検出・修正

## 出品ルール
- **1日の出品目標: 80品**
- タイトル: 英語、80文字以内、主要キーワード前方配置
- Condition: 正確に記載（NM, PSA10 等）
- SHIPPING WORLDWIDE 必須
- Promoted Listings: 3% 標準設定
- Item Specifics: 可能な限り埋める

## タイトル構成
```
[ブランド] [商品名] [レアリティ] [状態] [言語] - [カテゴリ]
例: One Piece Carddass Holo Prism 1999 NM Japanese - Trading Card
例: Shohei Ohtani PSA 10 Rookie Card 2018 Topps
```

## Slack通知
- 出品完了通知:「○月○日、○品出品しました」

## 使用ツール
- `ebay_lister.py` - eBay出品
- `export_lister.py` / `batch_export_lister.py` - 一括出品
- `auto_lister.py` - 自動出品
- `ebay_updater.py` - 価格更新
- `bulk_repair_titles.py` - タイトル一括修正
- `translator.py` - 翻訳

## レポート先
CEO（週次）、マーケティング部（出品状況共有）
