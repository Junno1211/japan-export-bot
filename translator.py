# ============================================================
#  translator.py  —  日本語 → 英語自動翻訳＆eBay用HTML生成
# ============================================================

from deep_translator import GoogleTranslator
import logging

logger = logging.getLogger(__name__)

def translate_to_english(text: str) -> str:
    """
    日本語のテキストを英語に自動翻訳する（無料のGoogle翻訳APIを使用）
    """
    if not text or not text.strip():
        return ""
        
    try:
        # 5000文字の制限があるため、長すぎる場合は切り詰め（通常の商品説明なら収まるはずです）
        if len(text) > 4900:
            text = text[:4900]
            
        translated = GoogleTranslator(source='ja', target='en').translate(text)
        return translated
    except Exception as e:
        logger.error(f"翻訳エラー: {e}")
        return text  # エラー時は原文を返す


def create_ebay_description(title_en: str, desc_ja: str) -> str:
    """
    eBay出品用の見栄えの良いHTML説明文テンプレートを生成する
    """
    logger.info("商品説明文を英語へ翻訳中...")
    desc_en = translate_to_english(desc_ja)
    
    # eBayのDescriptionポリシーに合わせたモバイル対応のシンプルなHTML
    html = f"""
    <div style="font-family: Arial, '\30D2\30E9\30AE\30CE\89D2\30B4 ProN', sans-serif; padding: 20px; max-width: 800px; margin: 0 auto; color: #333;">
        <h2 style="color: #1a1a1a; border-bottom: 2px solid #e53238; padding-bottom: 10px;">{title_en}</h2>
        
        <div style="background-color: #f7f7f7; padding: 20px; border-radius: 8px; margin: 20px 0;">
            <h3 style="color: #333; margin-top: 0; font-size: 1.2rem;">Item Description</h3>
            <p style="line-height: 1.8; white-space: pre-wrap; font-size: 1rem;">{desc_en}</p>
        </div>
        
        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #ccc; font-size: 0.9rem; color: #555;">
            <h4 style="color: #333;">Shipping Information</h4>
            <p>We ship securely with tracking. Shipping costs are calculated based on the item price to cover international logistics and insurance.</p>
            
            <h4 style="color: #333; margin-top: 20px;">International Buyers - Please Note</h4>
            <p>Import duties, taxes, and charges are not included in the item price or shipping cost. These charges are the buyer's responsibility. Please check with your country's customs office to determine what these additional costs will be prior to bidding or buying.</p>
        </div>
    </div>
    """
    return html

if __name__ == "__main__":
    # 手動テスト用
    sample_ja = "こちらは限定品のフィギュアです。箱に少し擦れがありますが、本体は新品未開封です。"
    print("【翻訳テスト】")
    print(translate_to_english(sample_ja))
