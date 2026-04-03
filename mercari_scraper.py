import logging
import random
import time
from typing import Dict, Any
from playwright.sync_api import sync_playwright
from circuit_breaker import mercari_breaker

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

logger = logging.getLogger(__name__)

def scrape_mercari_item(url: str, delay: float = 2.0, playwright_browser=None) -> Dict[str, Any]:
    """
    メルカリのURLから商品情報を抽出する。
    playwright_browser が渡された場合はそれを再利用する（メモリ節約）。
    """
    logger.info(f"メルカリから商品情報を抽出中: {url}")
    
    result = {
        "success": False,
        "title": "",
        "price_jpy": 0,
        "description": "",
        "image_urls": [],
        "status": "active",
        "error": "",
        "image_bytes": []
    }

    if not mercari_breaker.can_proceed():
        logger.warning(f"[Mercari] Circuit breaker OPEN — skipping scrape for {url}")
        result["error"] = "Mercari circuit breaker OPEN"
        return result

    user_agent = random.choice(_USER_AGENTS)
    
    if playwright_browser:
        return _scrape_with_browser(playwright_browser, url, user_agent, result)
    else:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            try:
                return _scrape_with_browser(browser, url, user_agent, result)
            finally:
                browser.close()

def _scrape_with_browser(browser, url, user_agent, result):
    # Contextを毎回新しく作ることでキャッシュクリーンを保つ（ItemIDごとにクリーン）
    viewport_width = random.randint(1280, 1920)
    viewport_height = random.randint(720, 1080)
    context = browser.new_context(
        user_agent=user_agent,
        locale="ja-JP",
        viewport={"width": viewport_width, "height": viewport_height}
    )
    page = context.new_page()
    try:
        # タイムアウトを長めに設定
        page.goto(url, wait_until="load", timeout=45000)
        time.sleep(3) # 少し長めに待機

        # Rate limit / block detection
        page_content = page.content()
        if "お探しのページが見つかりません" in page_content or "アクセスが制限されています" in page_content:
            logger.warning(f"⚠️ Mercari rate limit detected for {url}")
            mercari_breaker.record_failure()
            result["error"] = "Rate limited by Mercari"
            return result

        # スクリーンショット（診断用）
        # page.screenshot(path="mercari_debug.png")

        # ========== 仕入れ可否チェック（無在庫転売の生命線） ==========
        # 売り切れ判定（複数手法で確実に検出）
        sold_check = page.evaluate("""() => {
            // 1. DOM内テキスト
            const body = document.body.innerText || '';
            if (body.includes('売り切れました') || body.includes('この商品は売り切れです')) return 'sold_text';
            // 2. JSON-LD
            const scripts = document.querySelectorAll('script[type="application/ld+json"]');
            for (const s of scripts) {
                try {
                    const j = JSON.parse(s.textContent);
                    if (j.offers && j.offers.availability && j.offers.availability.includes('OutOfStock')) return 'sold_jsonld';
                } catch(e) {}
            }
            // 3. メタタグ
            const meta = document.querySelector('meta[property="product:availability"]');
            if (meta && meta.content && (meta.content.includes('oos') || meta.content.includes('out'))) return 'sold_meta';
            // 4. __NEXT_DATA__（メルカリのNext.jsデータ）
            const nextScript = document.querySelector('script#__NEXT_DATA__');
            if (nextScript) {
                try {
                    const d = JSON.parse(nextScript.textContent);
                    const str = JSON.stringify(d);
                    if (str.includes('"status":"sold_out"') || str.includes('"status":"trading"')) return 'sold_nextdata';
                } catch(e) {}
            }
            // 5. 購入ボタンがない（販売中なら必ず存在）
            const buyBtn = document.querySelector('[data-testid="checkout-button"], mer-button[data-testid="buy"]');
            const soldBtn = document.querySelector('mer-button[disabled]');
            if (!buyBtn && soldBtn) return 'sold_nobuy';
            return '';
        }""")
        if sold_check:
            result["status"] = "sold_out"
            result["error"] = f"売り切れ商品({sold_check})"
            logger.warning(f"⛔ 売り切れ商品({sold_check}): {url}")
            return result

        # ========== オークション判定（6層検出 — 偽陰性ゼロを目指す） ==========
        # 注意: text='入札' は説明文中の「入札」にも反応するため使わない
        # 確実なシグナルのみ使用（「現在」テキストは固定価格にも出現するため使用禁止）:
        #   1. data-testid="auction" 要素の存在
        #   2. HTML内のJSON構造に item_trading_format:"auction" がある
        #   3. 「オークション」バッジ/タグ要素のテキスト検出
        #   4. __NEXT_DATA__ 内の item_type/trading_format チェック
        #   5. 入札ボタン/入札件数UIの存在
        is_auction = page.evaluate("""() => {
            // シグナル2: data-testid="auction" またはその部分一致
            if (document.querySelector('[data-testid="auction"]')) return 'testid_auction';
            if (document.querySelector('[data-testid*="auction"]')) return 'testid_partial';
            // シグナル3: HTML内のJSONデータ
            const html = document.documentElement.innerHTML || '';
            if (html.includes('"item_trading_format":"auction"') ||
                html.includes('"itemType":"auction"') ||
                html.includes('"item_type":"auction"')) return 'json_field';
            // シグナル4: 「オークション」バッジ — mer-badge, mer-tag, span等のUI要素
            const badgeSelectors = [
                'mer-badge', 'mer-tag', '[class*="badge"]', '[class*="tag"]',
                '[class*="Badge"]', '[class*="Tag"]', '[class*="label"]',
                '[class*="auction"]', '[data-testid*="badge"]',
            ];
            for (const sel of badgeSelectors) {
                const els = document.querySelectorAll(sel);
                for (const el of els) {
                    const txt = (el.innerText || el.textContent || '').trim();
                    if (txt.includes('オークション')) return 'badge_text';
                }
            }
            // シグナル5: __NEXT_DATA__ 内の構造化データ
            const nextScript = document.querySelector('script#__NEXT_DATA__');
            if (nextScript) {
                try {
                    const raw = nextScript.textContent;
                    if (raw.includes('"auction"')) {
                        const d = JSON.parse(raw);
                        const str = JSON.stringify(d);
                        if (str.includes('"item_trading_format":"auction"') ||
                            str.includes('"itemType":"auction"') ||
                            str.includes('"item_type":"auction"') ||
                            str.includes('"tradingFormat":"auction"')) return 'nextdata';
                    }
                } catch(e) {}
            }
            // シグナル6: 入札UI要素（入札ボタン、入札件数表示）
            const bidBtn = document.querySelector('[data-testid="bid-button"], [data-testid*="bid"]');
            if (bidBtn) return 'bid_button';
            const bidCount = document.querySelector('[class*="bidCount"], [class*="bid-count"], [data-testid*="bid-count"]');
            if (bidCount) return 'bid_count';
            return '';
        }""")
        if is_auction:
            result["status"] = "auction"
            result["error"] = f"オークション商品のためスキップ(検出:{is_auction})"
            logger.warning(f"⛔ オークション商品({is_auction}): {url}")
            return result
        # ==========================================================

        # ========== 最終ゲート: 「購入手続きへ」ボタン確認 ==========
        # 固定価格で販売中の商品には必ず「購入手続きへ」ボタンが存在する。
        # ボタンがない = 購入不可能 = 出品してはいけない。
        has_buy_button = page.evaluate("""() => {
            const body = document.body.innerText || '';
            if (body.includes('購入手続きへ')) return true;
            // data-testid でも確認
            const btn = document.querySelector('[data-testid="checkout-button"]');
            if (btn) return true;
            // mer-button 内テキスト
            const buttons = document.querySelectorAll('mer-button, button');
            for (const b of buttons) {
                const t = (b.innerText || b.textContent || '').trim();
                if (t.includes('購入手続き')) return true;
            }
            return false;
        }""")
        if not has_buy_button:
            result["status"] = "sold_out"
            result["error"] = "「購入手続きへ」ボタンなし — 購入不可"
            logger.warning(f"⛔ 購入手続きボタンなし: {url}")
            return result
        # ==========================================================

        # データ抽出 (より堅牢なセレクタ — 2026年対応)
        data = page.evaluate("""() => {
            const getPrice = () => {
                // 複数パターン対応
                const selectors = [
                    '[data-testid="price"]',
                    'span[class*="price"]',
                    'span[class*="number"]',
                    '[class*="Price"] span',
                    'mer-price',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText) {
                        const num = el.innerText.replace(/[^0-9]/g, '');
                        if (num && parseInt(num) > 0) return num;
                    }
                }
                // 最終フォールバック: ページ内のJSON-LDから取得
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                for (const s of scripts) {
                    try {
                        const j = JSON.parse(s.textContent);
                        if (j.offers && j.offers.price) return String(j.offers.price);
                        if (j.price) return String(j.price);
                    } catch(e) {}
                }
                // メタタグから取得
                const meta = document.querySelector('meta[property="product:price:amount"]');
                if (meta) return meta.content;
                return '0';
            };
            const getTitle = () => {
                const selectors = [
                    'h1[class*="itemName"]',
                    'h1[class*="heading"]',
                    'h1',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText && el.innerText.length > 2) return el.innerText.trim();
                }
                // OGタグから取得
                const og = document.querySelector('meta[property="og:title"]');
                if (og) return og.content.replace(' - メルカリ', '').trim();
                return document.title.replace(' - メルカリ', '').trim();
            };
            const getDesc = () => {
                const selectors = [
                    'pre[data-testid="description"]',
                    '[data-testid="description"]',
                    '[class*="description"]',
                    'mer-text[data-testid="description"]',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText && el.innerText.length > 5) return el.innerText;
                }
                // OGタグから取得
                const og = document.querySelector('meta[property="og:description"]');
                if (og) return og.content;
                return '';
            };

            const title = getTitle();
            const desc = getDesc();
            const price = getPrice();

            // 商品IDを抽出（URLから）
            const itemId = location.pathname.split('/item/')[1] || '';
            const imgs = Array.from(new Set(
                Array.from(document.querySelectorAll('img'))
                    .map(i => i.src)
                    .filter(s => s.includes('mercdn.net'))
                    .filter(s => s.includes('/item/') || s.includes('/photo/') || s.includes('/detail/'))
                    .filter(s => !itemId || s.includes(itemId))
            ));
            return { title, desc, price, imgs };
        }""")
        
        result["title"] = data["title"]
        result["description"] = data["desc"]
        result["price_jpy"] = int(data["price"])
        result["image_urls"] = data["imgs"]

        if not result["title"] or result["price_jpy"] == 0:
            # Title/Price取得不可 = 売り切れ/削除済みの可能性が高い
            # 販売中の固定価格商品なら必ず取得できるため、sold_outとして返す
            result["status"] = "sold_out"
            result["error"] = "Title/Price取得不可（売り切れの可能性）"
            logger.warning(f"⛔ データ取得不可→売り切れ扱い: {url}")
            return result

        # 画像ダウンロード（オリジナルURLをそのまま使う — 変換で壊さない）
        for img_url in data["imgs"][:12]:
            try:
                resp = context.request.get(img_url, timeout=15000)
                if resp.ok and len(resp.body()) > 1000:
                    result["image_bytes"].append({"url": img_url, "bytes": resp.body()})
            except Exception as e:
                logger.warning(f"Image download failed: {e}")
            
        result["success"] = True
        mercari_breaker.record_success()
        return result
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Scrape internal error: {e}")
        mercari_breaker.record_failure()
        return result
    finally:
        page.close()
        context.close()

if __name__ == "__main__":
    # 手動テスト用
    import sys
    if len(sys.argv) > 1:
        test_url = sys.argv[1]
        data = scrape_mercari_item(test_url)
        print(data)
