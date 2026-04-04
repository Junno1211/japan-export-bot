# ============================================================
#  mercari_checker.py  —  メルカリ在庫チェック（requests版）
# ============================================================

import re
import time
import logging
import requests

logger = logging.getLogger(__name__)


def _check_auction_by_playwright(url: str) -> bool:
    """API/HTMLで判定できない場合のPlaywrightフォールバック（オークション検出専用）"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = browser.new_context(locale="ja-JP")
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="load", timeout=30000)
                time.sleep(2)
                is_auction = page.evaluate("""() => {
                    if (document.querySelector('[data-testid="auction"]')) return true;
                    if (document.querySelector('[data-testid*="auction"]')) return true;
                    const sels = ['mer-badge','mer-tag','[class*="badge"]','[class*="tag"]','[class*="auction"]'];
                    for (const sel of sels) {
                        for (const el of document.querySelectorAll(sel)) {
                            if ((el.innerText||'').includes('オークション')) return true;
                        }
                    }
                    if (document.querySelector('[data-testid*="bid"]')) return true;
                    const html = document.documentElement.innerHTML || '';
                    if (html.includes('"item_trading_format":"auction"') ||
                        html.includes('"item_type":"auction"')) return true;
                    return false;
                }""")
                return bool(is_auction)
            finally:
                page.close()
                ctx.close()
                browser.close()
    except Exception as e:
        logger.warning(f"Playwright auction check failed: {e}")
        return False

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ja-JP,ja;q=0.9",
    "DPoP-Nonce": "",
    "X-Platform": "web",
}


from typing import Optional

def extract_mercari_item_id(url: str) -> Optional[str]:
    match = re.search(r'/item/(m\d+)', url)
    if match:
        return match.group(1)
    return None


def check_mercari_status(url: str, delay: float = 2.0) -> dict:
    """
    メルカリ商品のステータスをAPIで確認する。

    Returns:
        {"status": "active"|"sold_out"|"deleted"|"error", "title": str, "price": str}
    """
    time.sleep(delay)

    item_id = extract_mercari_item_id(url)

    # メルカリShops対応（item_idが取れない場合はHTMLで確認）
    if not item_id:
        return _check_by_html(url)

    try:
        api_url = f"https://api.mercari.jp/v2/items/{item_id}"
        resp = requests.get(api_url, headers=HEADERS, timeout=15)

        if resp.status_code == 404:
            return {"status": "deleted", "title": "", "price": ""}

        if resp.status_code != 200:
            # Playwright内から呼ばれる場合ネストエラーになるため、
            # APIが使えない場合はerrorを返す（呼び出し元で判断）
            return {"status": "error", "title": "", "price": "", "error": f"API {resp.status_code}"}

        data = resp.json().get("data", {})
        status = data.get("status", "")
        name = data.get("name", "")
        price = str(data.get("price", ""))

        # ========== オークション判定（厳格: 確実な証拠のみ） ==========
        # 注意: end_dateは固定価格商品にも存在するため判定に使わない
        item_type = str(data.get("item_type", "")).lower()
        item_trading_format = str(data.get("item_trading_format", "")).lower()
        num_bids = data.get("num_bids", 0)
        is_auction = (
            item_type == "auction"
            or item_trading_format == "auction"
            or (isinstance(num_bids, int) and num_bids > 0)
        )
        if is_auction:
            logger.warning(f"⛔ オークション商品検出(API): {url} item_type={item_type} format={item_trading_format} bids={num_bids}")
            return {"status": "auction", "title": name, "price": price}
        # ====================================================

        # status: "on_sale" = 販売中, "sold_out" = 売り切れ, "trading" = 取引中
        if status in ("sold_out", "trading", "stop"):
            return {"status": "sold_out", "title": name, "price": price}
        elif status == "on_sale":
            return {"status": "active", "title": name, "price": price}
        else:
            # 不明なステータスはHTMLで確認
            return _check_by_html(url)

    except requests.exceptions.Timeout:
        logger.warning(f"Timeout: {url}")
        return {"status": "error", "title": "", "price": "", "error": "timeout"}
    except Exception as e:
        logger.error(f"Error: {url} -> {e}")
        return {"status": "error", "title": "", "price": "", "error": str(e)}


def _check_by_html(url: str) -> dict:
    """HTMLフォールバック: Playwrightで「購入手続きへ」ボタンの有無のみで判定"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = browser.new_context(locale="ja-JP", user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)")
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="load", timeout=30000)
                time.sleep(3)

                # タイトル取得
                title = page.evaluate("""() => {
                    const h1 = document.querySelector('h1');
                    if (h1) return h1.innerText.trim();
                    const og = document.querySelector('meta[property="og:title"]');
                    if (og) return og.content.replace(' - メルカリ', '').trim();
                    return '';
                }""")

                # 「購入手続きへ」ボタンが存在するかどうかだけで判定
                has_buy_button = page.evaluate("""() => {
                    const buttons = document.querySelectorAll('button, mer-button, a');
                    for (const b of buttons) {
                        const text = (b.innerText || b.textContent || '').trim();
                        if (text.includes('購入手続きへ') || text.includes('購入する')) return true;
                    }
                    return false;
                }""")

                if has_buy_button:
                    return {"status": "active", "title": title, "price": ""}
                else:
                    return {"status": "sold_out", "title": title, "price": ""}

            finally:
                page.close()
                ctx.close()
                browser.close()

    except Exception as e:
        logger.error(f"HTML check error: {e}")
        return {"status": "sold_out", "title": "", "price": ""}


def batch_check_mercari(items: list[dict], delay: float = 2.0) -> list[dict]:
    results = []
    for i, item in enumerate(items):
        url = item.get("mercari_url", "")
        if not url:
            continue
        logger.info(f"[{i+1}/{len(items)}] チェック中: {url}")
        result = check_mercari_status(url, delay=delay)
        results.append({**item, **result})
        status_emoji = {"active": "✅", "sold_out": "❌", "deleted": "🗑️", "error": "⚠️"}.get(result["status"], "?")
        logger.info(f"  {status_emoji} {result['status']}: {result.get('title', '')[:40]}")
    return results
