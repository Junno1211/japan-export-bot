# ============================================================
#  mercari_checker.py  —  メルカリ在庫チェック（requests版）
# ============================================================

import json
import os
import time
import logging
import requests
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from config import (
    MERCARI_PAGE_GOTO_TIMEOUT_MS,
    MERCARI_V2_HEAD_TIMEOUT_SEC,
    MERCARI_V2_PENDING_PATH,
)

from feature_a import extract_mercari_item_id
from mercari_proxy import playwright_launch_kwargs, requests_proxies

logger = logging.getLogger(__name__)


def _requests_get(url: str, **kwargs):
    px = requests_proxies()
    if px:
        kwargs.setdefault("proxies", px)
    return requests.get(url, **kwargs)


def _requests_head(url: str, **kwargs):
    px = requests_proxies()
    if px:
        kwargs.setdefault("proxies", px)
    return requests.head(url, **kwargs)


def _check_auction_by_playwright(url: str) -> bool:
    """API/HTMLで判定できない場合のPlaywrightフォールバック（オークション検出専用）"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            _launch = dict(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            _launch.update(playwright_launch_kwargs())
            browser = p.chromium.launch(**_launch)
            ctx = browser.new_context(locale="ja-JP")
            page = ctx.new_page()
            try:
                from utils.phase0_guards import playwright_goto_with_retry

                playwright_goto_with_retry(
                    page, url, wait_until="load", timeout_ms=30000, attempts=2
                )
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


def check_mercari_status(url: str, delay: float = 2.0, playwright_browser=None) -> dict:
    """
    メルカリ商品のステータスをAPIで確認する。

    playwright_browser:
        Playwright の同期 API Browser（既に起動済み）。呼び出し元が sync_playwright 内のとき渡す。
        HTML フォールバックでは browser.new_context() だけ行い sync_playwright は起動しない。
        省略時は HTML 用に専用スレッドで sync_playwright を起動する。

    Returns:
        {"status": "active"|"sold_out"|"deleted"|"auction"|"error"|"html_error", ...}
    """
    time.sleep(delay)

    item_id = extract_mercari_item_id(url)

    # メルカリShops対応（item_idが取れない場合はHTMLで確認）
    if not item_id:
        return _check_by_html(url, playwright_browser=playwright_browser)

    try:
        api_url = f"https://api.mercari.jp/v2/items/{item_id}"
        resp = _requests_get(api_url, headers=HEADERS, timeout=15)

        if resp.status_code == 404:
            return {"status": "deleted", "title": "", "price": ""}

        if resp.status_code == 429:
            from utils.phase0_guards import rate_limit_guard

            rate_limit_guard(resp, "Mercari JSON API")

        if resp.status_code >= 500:
            logger.warning("Mercari API %s for item — Phase0: no HTML fallback", resp.status_code)
            return {
                "status": "error",
                "title": "",
                "price": "",
                "error": f"api_http_{resp.status_code}",
            }

        if resp.status_code != 200:
            return _check_by_html(url, playwright_browser=playwright_browser)

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
            return _check_by_html(url, playwright_browser=playwright_browser)

    except requests.exceptions.Timeout:
        logger.warning(f"Timeout: {url}")
        return {"status": "error", "title": "", "price": "", "error": "timeout"}
    except Exception as e:
        logger.error(f"Error: {url} -> {e}")
        return {"status": "error", "title": "", "price": "", "error": str(e)}


def _mercari_api_item_snapshot_no_html(item_id: str) -> dict:
    """
    Phase 0 二系統用: item_id が取れる場合のみ API を叩く（HTML フォールバックなし・再帰なし）。
    """
    try:
        api_url = f"https://api.mercari.jp/v2/items/{item_id}"
        resp = _requests_get(api_url, headers=HEADERS, timeout=15)
        if resp.status_code == 429:
            from utils.phase0_guards import rate_limit_guard

            rate_limit_guard(resp, "Mercari JSON API")
        if resp.status_code == 404:
            return {"status": "deleted", "title": "", "price": ""}
        if resp.status_code >= 500 or resp.status_code != 200:
            return {
                "status": "error",
                "title": "",
                "price": "",
                "error": f"api_http_{resp.status_code}",
            }
        data = resp.json().get("data", {})
        status = data.get("status", "")
        name = data.get("name", "")
        price = str(data.get("price", ""))
        item_type = str(data.get("item_type", "")).lower()
        item_trading_format = str(data.get("item_trading_format", "")).lower()
        num_bids = data.get("num_bids", 0)
        is_auction = (
            item_type == "auction"
            or item_trading_format == "auction"
            or (isinstance(num_bids, int) and num_bids > 0)
        )
        if is_auction:
            return {"status": "auction", "title": name, "price": price}
        if status in ("sold_out", "trading", "stop"):
            return {"status": "sold_out", "title": name, "price": price}
        if status == "on_sale":
            return {"status": "active", "title": name, "price": price}
        return {"status": "error", "title": name, "price": price, "error": f"api_unknown_status:{status}"}
    except requests.exceptions.Timeout:
        return {"status": "error", "title": "", "price": "", "error": "api_timeout"}
    except Exception as e:
        return {"status": "error", "title": "", "price": "", "error": str(e)}


def _html_buy_button_result(page, url: str) -> dict:
    """
    実ページで「購入手続きへ」が表示されているかで判定し、
    Phase 0 では item_id が取れる場合に API と二系統突合してから sold_out を返す。
    """
    from utils.phase0_guards import playwright_goto_with_retry

    playwright_goto_with_retry(
        page, url, wait_until="load", timeout_ms=30000, attempts=2
    )
    time.sleep(3)

    title = page.evaluate("""() => {
        const h1 = document.querySelector('h1');
        if (h1) return h1.innerText.trim();
        const og = document.querySelector('meta[property="og:title"]');
        if (og) return og.content.replace(' - メルカリ', '').trim();
        return '';
    }""")

    # 非表示DOMに残った「購入手続きへ」で在庫ありと誤判定しないよう、表示中の要素のみ見る
    has_kounyuu = page.evaluate("""() => {
        function visible(el) {
            const s = window.getComputedStyle(el);
            if (s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0) {
                return false;
            }
            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) return false;
            return true;
        }
        const buyHints = ['購入手続きへ', '購入に進む', '今すぐ購入'];
        const buttons = document.querySelectorAll('button, mer-button, a, [role="button"]');
        for (const b of buttons) {
            if (!visible(b)) continue;
            const text = (b.innerText || b.textContent || '').trim();
            for (const h of buyHints) {
                if (text.includes(h)) return true;
            }
        }
        return false;
    }""")

    if has_kounyuu:
        return {"status": "active", "title": title, "price": ""}

    mid = extract_mercari_item_id(url)
    if mid:
        api_snap = _mercari_api_item_snapshot_no_html(mid)
        ast = api_snap.get("status", "error")
        if ast == "active":
            return {
                "status": "html_error",
                "title": title,
                "price": "",
                "error": "phase0_no_cta_but_api_on_sale",
            }
        if ast in ("error",):
            return {
                "status": "html_error",
                "title": title,
                "price": "",
                "error": api_snap.get("error", "api_indeterminate"),
            }
        if ast in ("sold_out", "deleted", "auction"):
            return {
                "status": ast,
                "title": title or api_snap.get("title", ""),
                "price": api_snap.get("price", ""),
            }
        return {
            "status": "html_error",
            "title": title,
            "price": "",
            "error": f"phase0_no_cta_api_unexpected:{ast}",
        }

    return {
        "status": "html_error",
        "title": title,
        "price": "",
        "error": "phase0_no_cta_no_item_id",
    }


def check_stock_by_purchase_button(url: str, delay: float = 0.5) -> dict:
    """
    メルカリ API は使わず、Playwright でページを開き「購入手続きへ」の有無だけを見る。
    在庫管理・safe_restock の正とする。
    """
    time.sleep(delay)
    return _run_playwright_html_single(url)


def _run_playwright_html_single(url: str) -> dict:
    """
    Playwright Sync API は asyncio イベントループ上のスレッドでは動かない。
    専用ワーカースレッドで起動し、誤判定による在庫0を防ぐ。
    """
    def inner() -> dict:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                _launch = dict(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                _launch.update(playwright_launch_kwargs())
                browser = p.chromium.launch(**_launch)
                ctx = browser.new_context(
                    locale="ja-JP",
                    user_agent=HEADERS["User-Agent"],
                )
                page = ctx.new_page()
                try:
                    return _html_buy_button_result(page, url)
                finally:
                    page.close()
                    ctx.close()
                    browser.close()
        except Exception as e:
            logger.error(f"HTML check error: {e}")
            return {"status": "html_error", "title": "", "price": "", "error": str(e)}

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(inner).result(timeout=120)


def html_verify_urls(urls: List[str]) -> Dict[str, dict]:
    """
    複数 URL を同一ブラウザで順に HTML 確認（在庫管理のバッチ用）。
    メインスレッドをブロックしないよう、処理全体を 1 本のワーカーに閉じる。
    """
    if not urls:
        return {}
    unique_urls = list(dict.fromkeys(urls))

    def batch_inner() -> Dict[str, dict]:
        out: Dict[str, dict] = {}
        try:
            from playwright.sync_api import sync_playwright

            playwright = sync_playwright().start()
            try:
                _launch = dict(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                _launch.update(playwright_launch_kwargs())
                browser = playwright.chromium.launch(**_launch)
                try:
                    for url in unique_urls:
                        try:
                            ctx = browser.new_context(
                                locale="ja-JP",
                                user_agent=HEADERS["User-Agent"],
                            )
                            page = ctx.new_page()
                            try:
                                out[url] = _html_buy_button_result(page, url)
                            finally:
                                page.close()
                                ctx.close()
                        except Exception as e:
                            logger.error(f"HTML check error for {url}: {e}")
                            out[url] = {
                                "status": "html_error",
                                "title": "",
                                "price": "",
                                "error": str(e),
                            }
                finally:
                    browser.close()
            finally:
                playwright.stop()
        except Exception as e:
            logger.error(f"HTML batch worker fatal: {e}")
            for u in unique_urls:
                if u not in out:
                    out[u] = {
                        "status": "html_error",
                        "title": "",
                        "price": "",
                        "error": str(e),
                    }
        return out

    timeout = max(120, min(3600, len(unique_urls) * 90))
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(batch_inner).result(timeout=timeout)


def _check_by_html(url: str, playwright_browser=None) -> dict:
    """HTMLフォールバック: Playwrightで「購入手続きへ」ボタンの有無のみで判定"""
    if playwright_browser is not None:
        try:
            ctx = playwright_browser.new_context(
                locale="ja-JP",
                user_agent=HEADERS["User-Agent"],
            )
            page = ctx.new_page()
            try:
                return _html_buy_button_result(page, url)
            finally:
                page.close()
                ctx.close()
        except Exception as e:
            logger.error(f"HTML check error: {e}")
            return {"status": "html_error", "title": "", "price": "", "error": str(e)}
    return _run_playwright_html_single(url)


# ============================================================
#  mercari OOS 判定 v2（在庫管理専用）
#  timeout ≠ sold / 単発では eBay OOS 禁止 / 二回 sold_strict のみ確定
# ============================================================


def mercari_head_stage1(url: str) -> dict:
    """
    段階1: HTTP HEAD。404=削除確定、timeout/5xx/非200=ambiguous（sold 扱いしない）。
    """
    try:
        resp = _requests_head(
            url,
            timeout=MERCARI_V2_HEAD_TIMEOUT_SEC,
            allow_redirects=True,
            headers={"User-Agent": HEADERS["User-Agent"]},
        )
    except requests.exceptions.Timeout:
        return {"outcome": "ambiguous", "reason": "head_timeout"}
    except requests.RequestException as e:
        return {"outcome": "ambiguous", "reason": f"head_error:{e}"}

    sc = int(resp.status_code)
    try:
        from utils.phase0_guards import log_http_status

        log_http_status(url, sc, "mercari_head_stage1")
    except Exception:
        pass
    if sc == 404:
        return {"outcome": "deleted"}
    if sc >= 500:
        return {"outcome": "ambiguous", "reason": f"http_{sc}"}
    if sc != 200:
        return {"outcome": "ambiguous", "reason": f"http_{sc}"}
    return {"outcome": "200"}


def _playwright_eval_stage2_strict_sold(page, url: str) -> dict:
    """
    段階2: 3 条件 AND のみ sold_strict。欠ける・オークション疑いは ambiguous / auction。
    """
    goto_ms = max(15000, min(int(MERCARI_PAGE_GOTO_TIMEOUT_MS), 120000))
    from utils.phase0_guards import playwright_goto_with_retry

    playwright_goto_with_retry(
        page, url, wait_until="load", timeout_ms=goto_ms, attempts=2
    )
    time.sleep(2.5)
    data = page.evaluate(
        """() => {
        function visible(el) {
            if (!el) return false;
            const s = window.getComputedStyle(el);
            if (s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0) return false;
            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) return false;
            return true;
        }
        const html = document.documentElement.innerHTML || '';
        if (html.includes('"item_trading_format":"auction"') || html.includes('"item_type":"auction"')) {
            return { kind: 'auction' };
        }
        let soldLabel = false;
        const cands = document.querySelectorAll('[data-testid*="sold" i], mer-badge, mer-tag, [class*="badge" i], [class*="Badge" i], [class*="Status" i]');
        for (const el of cands) {
            if (!visible(el)) continue;
            const t = ((el.innerText || el.textContent || '').trim()).toUpperCase();
            if (t === 'SOLD' || t.includes('SOLD')) { soldLabel = true; break; }
        }
        const bodyText = (document.body && document.body.innerText) ? document.body.innerText : '';
        const hasSoldPhrase = bodyText.includes('売り切れました');
        const buyHints = ['購入手続きへ', '購入に進む', '今すぐ購入'];
        let hasActiveBuy = false;
        for (const b of document.querySelectorAll('button, mer-button, a, [role="button"]')) {
            if (!visible(b)) continue;
            const text = (b.innerText || b.textContent || '').trim();
            for (const h of buyHints) {
                if (!text.includes(h)) continue;
                const mer = b.closest('mer-button');
                const dis = b.disabled || b.getAttribute('aria-disabled') === 'true'
                    || (mer && mer.hasAttribute && mer.hasAttribute('disabled'));
                if (!dis) { hasActiveBuy = true; }
                break;
            }
        }
        const soldStrict = !!(soldLabel && hasSoldPhrase && !hasActiveBuy);
        if (soldStrict) return { kind: 'sold_strict' };
        if (hasActiveBuy) return { kind: 'available' };
        return { kind: 'ambiguous_dom', soldLabel, hasSoldPhrase, hasActiveBuy };
    }"""
    )
    return data if isinstance(data, dict) else {"kind": "ambiguous_dom"}


def _mercari_oos_playwright_stage2_only(url: str) -> dict:
    """HEAD=200 済み前提で Playwright 段階2のみ。例外は ambiguous。"""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            _launch = dict(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            _launch.update(playwright_launch_kwargs())
            browser = p.chromium.launch(**_launch)
            ctx = browser.new_context(
                locale="ja-JP",
                user_agent=HEADERS["User-Agent"],
            )
            page = ctx.new_page()
            try:
                ev = _playwright_eval_stage2_strict_sold(page, url)
            finally:
                page.close()
                ctx.close()
                browser.close()
    except Exception as e:
        err = str(e).lower()
        if "timeout" in err:
            return {"verdict": "ambiguous", "reason": "playwright_timeout"}
        logger.warning("mercari_oos v2 playwright: %s", e)
        return {"verdict": "ambiguous", "reason": f"playwright_error:{e}"}

    kind = ev.get("kind", "")
    if kind == "auction":
        return {"verdict": "auction", "reason": "dom_auction"}
    if kind == "sold_strict":
        return {"verdict": "sold_tentative", "reason": "strict_and_pass"}
    if kind == "available":
        return {"verdict": "active", "reason": "buy_visible"}
    return {"verdict": "ambiguous", "reason": "dom_incomplete", "detail": ev}


def mercari_oos_verdict_pass1(url: str) -> dict:
    """在庫OOS 用 1 回目（単独では eBay に触れない想定で呼ぶ）。"""
    h = mercari_head_stage1(url)
    if h["outcome"] == "deleted":
        return {"verdict": "deleted", "reason": "head_404"}
    if h["outcome"] != "200":
        return {"verdict": "ambiguous", "reason": h.get("reason", "head")}

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_mercari_oos_playwright_stage2_only, url).result(timeout=150)


def mercari_oos_verdict_pass2(url: str) -> dict:
    """5 分後など別コンテキスト用。ロジックは pass1 と同型（新ブラウザで再取得）。"""
    return mercari_oos_verdict_pass1(url)


def mercari_v2_load_pending(path: Optional[str] = None) -> List[dict]:
    p = path or MERCARI_V2_PENDING_PATH
    if not os.path.isfile(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning("mercari_v2_load_pending: %s", e)
        return []


def mercari_v2_save_pending(rows: List[dict], path: Optional[str] = None) -> None:
    p = path or MERCARI_V2_PENDING_PATH
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def mercari_v2_add_pending(entry: dict, path: Optional[str] = None) -> None:
    eid = (entry.get("ebay_id") or "").strip()
    rows = mercari_v2_load_pending(path)
    rows = [r for r in rows if (r.get("ebay_id") or "").strip() != eid]
    rows.append(entry)
    mercari_v2_save_pending(rows, path)


def batch_check_mercari(items: list[dict], delay: float = 2.0) -> list[dict]:
    results = []
    for i, item in enumerate(items):
        url = item.get("mercari_url", "")
        if not url:
            continue
        logger.info(f"[{i+1}/{len(items)}] チェック中: {url}")
        result = check_mercari_status(url, delay=delay)
        results.append({**item, **result})
        status_emoji = {
            "active": "✅",
            "sold_out": "❌",
            "deleted": "🗑️",
            "error": "⚠️",
            "html_error": "🔧",
        }.get(result["status"], "?")
        logger.info(f"  {status_emoji} {result['status']}: {result.get('title', '')[:40]}")
    return results
