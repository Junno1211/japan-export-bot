import os
import re
import time
import json
import random
import logging
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from playwright.sync_api import sync_playwright
from typing import Optional, List

from config import (
    GOOGLE_CREDENTIALS_PATH, SPREADSHEET_ID, AUTO_SHEET_NAME,
    AUTO_SHEET_CARD, AUTO_SHEET_HOBBY, AUTO_SHEET_OTHER,
    EBAY_APP_ID, EXCHANGE_RATE
)
from sheets_manager import _get_service, create_sheet_if_not_exists
from auto_lister import calc_profit
from ebay_price_checker import (
    get_winning_titles,
    get_market_price,
    get_sold_velocity,
    resolve_reference_sold_price_usd,
    median_sold_price_usd,
)
from heartbeat import update_heartbeat
from supervisor import validate_sourcing
from mercari_checker import check_mercari_status

load_dotenv()

PROFIT_THRESHOLD = 3000 # 最低利益¥3,000。目標¥3,000〜5,000/品（部署で min_profit_jpy があれば上書き）
MAX_ITEMS_PER_KEYWORD = 10
SEEN_FILE = "seen_ids.json"

# --max-additions 用（1実行あたりのシート追加上限・global 回避）
_SOURCING_RUN = {"max_additions": None, "added": 0}


def sourcing_budget_exhausted() -> bool:
    m = _SOURCING_RUN["max_additions"]
    return m is not None and _SOURCING_RUN["added"] >= m

NG_KEYWORDS = ["ダンボール", "ジャンク", "大箱", "重量", "大型", "等身大", "動作未確認", "不動", "部品取り", "訳あり", "状態が悪い", "故障",
               "まとめ売り", "まとめて", "セット売り", "大量", "引退", "処分", "bulk", "lot", "枚セット", "枚まとめ", "100枚", "200枚", "300枚", "500枚", "1000枚",
               "damaged", "broken", "junk", "defective", "fake", "replica", "counterfeit", "bootleg",
               "傷あり", "汚れあり", "破損", "欠品", "読み込み不可", "動作不良", "難あり", "キズ", "ヒビ",
               "非正規", "コピー品", "海賊版", "模造品"]
SAFE_CARD_KEYWORDS = ["カード", "トレカ", "ポケカ", "遊戯王", "デュエマ", "ワンピースカード", "psa", "ピカチュウ", "デッキ"]
JP_CARD_KEYWORDS = ["bbm", "epoch", "カルビー", "バンダイ", "カードダス", "日本限定", "日本製", "npb", "プロ野球", "大谷翔平", "日本ハム", "wbc"]

SOURCING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sourcing")


def load_department_keywords() -> list:
    """sourcing/*/keywords.json を全部署分読み込む"""
    departments = []
    if not os.path.isdir(SOURCING_DIR):
        return departments
    for dept_name in sorted(os.listdir(SOURCING_DIR)):
        dept_dir = os.path.join(SOURCING_DIR, dept_name)
        kw_file = os.path.join(dept_dir, "keywords.json")
        if os.path.isdir(dept_dir) and os.path.exists(kw_file):
            try:
                with open(kw_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["_dir"] = dept_name
                departments.append(data)
                logger.info(f"📂 部署読み込み: {data.get('department', dept_name)} ({len(data.get('mercari_keywords', []))}件)")
            except Exception as e:
                logger.error(f"keywords.json 読み込みエラー ({dept_name}): {e}")
    return departments

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def load_seen_ids() -> set:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except: return set()
    return set()

def save_seen_ids(seen_ids: set):
    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(SEEN_FILE)) or ".", suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(list(seen_ids), f, indent=2)
        os.replace(tmp_path, SEEN_FILE)
    except:
        os.unlink(tmp_path)
        raise

def is_url_already_listed(url: str) -> bool:
    """在庫管理表・全自動出品シート・items.csvに同じURLが既にあるか"""
    import csv as _csv
    target = url.strip()
    try:
        service = _get_service()
        # 在庫管理表チェック（D列が仕入先URL）
        res1 = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range='在庫管理表!D2:D5000'
        ).execute()
        existing_urls = {r[0].strip() for r in res1.get('values', []) if r}
        if target in existing_urls:
            return True
        # 全自動出品シートチェック（A列がURL）
        for sn in [AUTO_SHEET_NAME, AUTO_SHEET_CARD, AUTO_SHEET_HOBBY, AUTO_SHEET_OTHER]:
            try:
                res = service.spreadsheets().values().get(
                    spreadsheetId=SPREADSHEET_ID, range=f'{sn}!A2:A5000'
                ).execute()
                sheet_urls = {r[0].strip() for r in res.get('values', []) if r}
                if target in sheet_urls:
                    return True
            except:
                pass
        # items.csvチェック
        csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "items.csv")
        if os.path.exists(csv_path):
            with open(csv_path, "r") as f:
                for row in _csv.DictReader(f):
                    if row.get("mercari_url", "").strip() == target:
                        return True
    except:
        pass
    return False


CARD_WORDS = ["カード", "トレカ", "ポケカ", "遊戯王", "デュエマ", "ワンピースカード", "psa", "bbm", "epoch",
              "カルビー", "カードダス", "大谷", "ohtani", "pokemon", "one piece", "card", "promo", "holo", "prism",
              "相撲", "sumo", "大の里", "白鵬", "宇良", "青錦", "鳳龍"]
HOBBY_WORDS = ["ガンダム", "gundam", "漫画", "manga", "フィギュア", "figure", "プラモ", "アニメ", "anime",
               "ナルト", "naruto", "ハイキュー", "nana", "デジモン", "digimon", "グッズ", "キーホルダー"]

def detect_genre_sheet(title: str, dept_name: str = "") -> str:
    """タイトルと部署名からジャンル別シートを判定"""
    text = (title + " " + dept_name).lower()
    if any(w in text for w in CARD_WORDS):
        return AUTO_SHEET_CARD
    if any(w in text for w in HOBBY_WORDS):
        return AUTO_SHEET_HOBBY
    return AUTO_SHEET_OTHER


def append_to_auto_sheet(url: str, profit: int, title: str, mercari_price: int, basis: str) -> bool:
    """
    ジャンル別の自動出品タブにリサーチ結果を反映
    A: URL, B: 期待利益(円), C: (空), D: eBayItemID, E: Status, F: Notes
    Returns True if 1行追加した
    """
    # === SUPERVISOR: リサーチ結果の検証 ===
    sv_result = validate_sourcing(
        mercari_url=url,
        mercari_price_jpy=mercari_price,
        profit_jpy=profit,
        title=title,
    )
    if not sv_result["approved"]:
        logger.info(f"🚫 [SUPERVISOR] ブロック: {title[:30]}... 理由: {sv_result['violations']}")
        return False

    # 重複チェック
    if is_url_already_listed(url):
        logger.info(f"⏭️ 重複スキップ: {title[:30]}...")
        return False

    # ジャンル判定
    sheet_name = detect_genre_sheet(title, basis)

    try:
        service = _get_service()
        create_sheet_if_not_exists(sheet_name)
        row_data = [url, profit, "", "", "完了", f"【根拠】{basis} | {title} (¥{mercari_price:,})"]

        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range=f"{sheet_name}!A:A"
        ).execute()
        next_row = len(result.get('values', [])) + 1
        if next_row < 2: next_row = 2

        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID, range=f"{sheet_name}!A{next_row}:F{next_row}",
            valueInputOption="USER_ENTERED", body={"values": [row_data]}
        ).execute()
        logger.info(f"✅ [{sheet_name}] 追加: {title[:30]}... 利益¥{profit:,} ({basis})")
        return True
    except Exception as e:
        logger.error(f"Sheet Append Error: {e}")
        return False

def get_mercari_items_with_retry(page, url, max_retries=3):
    """3回のリトライと指数バックオフを備えた堅牢なスクレイピング"""
    for attempt in range(max_retries):
        try:
            logger.info(f"  📥 抽出試行 {attempt+1}/{max_retries}: {url[:60]}...")
            # networkidle はトラッキング等で止まるため load + sleep が安全
            page.goto(url, wait_until="load", timeout=30000)
            time.sleep(3) # レンダリング待ち
            
            items = page.evaluate("""() => {
                const results = [];
                // data-testid="item-cell" が基本だが、無い場合は全 a タグを走査
                const cells = document.querySelectorAll('li[data-testid="item-cell"]');
                if (cells.length > 0) {
                    for (const li of cells) {
                        const a = li.querySelector('a[data-testid="thumbnail-link"]') || li.querySelector('a');
                        const priceSpan = li.querySelector('.merPrice span[class*="number"]') || li.querySelector('[class*="number"]');
                        if (a && priceSpan) {
                            results.push({
                                id: a.href.split('item/')[1],
                                url: a.href,
                                title: a.getAttribute('aria-label') || "",
                                price: parseInt(priceSpan.innerText.replace(/[^0-9]/g, ''), 10)
                            });
                        }
                    }
                } else {
                    // フォールバック: merPrice を持つ要素から親を辿る
                    const prices = document.querySelectorAll('.merPrice');
                    for (const p of prices) {
                        const a = p.closest('a');
                        if (a && a.href.includes('item/')) {
                            results.push({
                                id: a.href.split('item/')[1],
                                url: a.href,
                                title: a.getAttribute('aria-label') || "",
                                price: parseInt(p.innerText.replace(/[^0-9]/g, ''), 10)
                            });
                        }
                    }
                }
                return results;
            }""")
            if items: return items
            logger.warning(f"  ⚠️ 抽出結果が空です (Attempt {attempt+1})")
        except Exception as e:
            logger.error(f"  ❌ 試行 {attempt+1} 失敗: {e}")
            if attempt == max_retries - 1: raise e
        
        wait_time = (2 ** attempt) + random.random()
        time.sleep(wait_time)
    return []

def translate_to_english(japanese_text: str) -> str:
    """Geminiを使用してキーワードを英語に翻訳（eBay検索用）"""
    import requests as _req
    from config import GEMINI_API_KEY
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = f"Translate the following Japanese keyword to a single optimized eBay search query in English. Return ONLY the translated string: {japanese_text}"
    try:
        resp = _req.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
        if resp.status_code == 200:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip().replace('"', '')
    except:
        pass
    return japanese_text

def get_ebay_queries_for_dept(keyword: str, dept: Optional[dict] = None) -> List[str]:
    """
    部署設定がある場合: ebay_keywordsからキーワードに最も近いものを選び、
    さらにeBay Sold APIでWinning Titlesを取得する。
    部署設定がない場合: 従来通り翻訳→Winning Titles。
    """
    if dept and dept.get("ebay_keywords"):
        # 部署のeBayキーワードからメルカリキーワードに対応するものを選択
        # キーワードの主要語を含むeBayクエリを優先
        keyword_parts = keyword.lower().split()
        scored = []
        for eq in dept["ebay_keywords"]:
            eq_lower = eq.lower()
            score = sum(1 for p in keyword_parts if p in eq_lower)
            scored.append((score, eq))
        scored.sort(reverse=True, key=lambda x: x[0])
        # 最もマッチするeBayキーワードでWinning Titlesを取得
        best_query = scored[0][1] if scored else dept["ebay_keywords"][0]
        winning = get_winning_titles(best_query)
        if winning:
            return winning
        return [best_query]
    else:
        en_keyword = translate_to_english(keyword)
        winning = get_winning_titles(en_keyword)
        return winning if winning else [en_keyword]


def _build_similar_sold_queries(dept: Optional[dict], mercari_keyword: str) -> List[str]:
    """同シリーズ・同年代BBM等の eBay 検索クエリ（Sold中央値のフォールバック用）"""
    out: List[str] = []
    if dept:
        out.extend(dept.get("ebay_similar_sold_queries") or [])
    ck = [str(c).lower() for c in (dept.get("card_keywords") or [])] if dept else []
    if "bbm" in ck:
        out.extend(
            [
                "Shohei Ohtani BBM Nippon Ham Fighters",
                "Shohei Ohtani BBM Japanese baseball card",
                "Shohei Ohtani BBM Hokkaido Fighters",
                "Shohei Ohtani BBM rookie card",
                "Shohei Ohtani BBM NPB",
            ]
        )
    for m in re.finditer(r"(20[0-2]\d|19\d{2})", mercari_keyword):
        y = m.group(1)
        out.insert(0, f"Shohei Ohtani BBM {y}")
    seen = set()
    uniq: List[str] = []
    for q in out:
        k = q.strip().lower()
        if k and k not in seen:
            seen.add(k)
            uniq.append(q.strip())
    return uniq


def calculate_competitive_price(market_price_usd: float, dept: Optional[dict] = None) -> float:
    """
    部署の価格戦略に基づいて競争力のある販売価格を決定する。
    - undercut_pct: 相場からX%下げてアンダーカット
    - min_usd / max_usd: 部署ごとの価格レンジ
    """
    if dept and dept.get("pricing_strategy"):
        strategy = dept["pricing_strategy"]
        undercut = strategy.get("undercut_pct", 3) / 100.0
        min_usd = strategy.get("min_usd", 25)
        max_usd = min(strategy.get("max_usd", 2499), 2499)
        price = market_price_usd * (1.0 - undercut)
        return max(min(price, max_usd), min_usd)
    else:
        return max(min(market_price_usd, 2499.0), 99.0)


def scrape_and_source(keyword: str, dept: Optional[dict] = None):
    """
    部署特化型リバースソーシング:
    1. 部署のebay_keywordsを直接使用（翻訳精度に依存しない）
    2. 部署のcard_keywordsで該当カテゴリのみ精密フィルタ
    3. 部署のpricing_strategyで競争力のある価格を算出
    4. 採算が合えば「自動出品」タブへ

    dept: 部署設定（keywords.json由来）。Noneなら従来の共通フィルタを使用。
    """
    dept_name = dept.get("department", "共通") if dept else "共通"
    logger.info(f"🔥 [{dept_name}] Reverse-Sourcing Start: {keyword}")
    if sourcing_budget_exhausted():
        logger.info(f"⏹️ 追加上限に達したためスキップ: {keyword}")
        return

    # 部署別フィルタ
    dept_ng = [w.lower() for w in dept.get("ng_keywords", [])] if dept else []
    dept_card_kw = [w.lower() for w in dept.get("card_keywords", [])] if dept else []
    dept_min_price = dept.get("min_mercari_price", 1000) if dept else 1000
    dept_max_price = dept.get("max_mercari_price", 250000) if dept else 250000
    min_sell_usd = dept.get("pricing_strategy", {}).get("min_usd", 99) if dept else 99
    profit_threshold = int(dept.get("min_profit_jpy", PROFIT_THRESHOLD)) if dept else PROFIT_THRESHOLD
    max_per_kw = int(dept.get("max_items_per_keyword", MAX_ITEMS_PER_KEYWORD)) if dept else MAX_ITEMS_PER_KEYWORD
    days_wide = int(dept.get("similar_sold_days_primary", 90)) if dept else 90
    days_similar = int(dept.get("similar_sold_days", 120)) if dept else 120
    min_sold_samples = int(dept.get("similar_sold_min_samples", 2)) if dept else 2
    similar_sold_queries = _build_similar_sold_queries(dept, keyword)

    # eBayクエリ取得（部署キーワード直接 or 翻訳）
    ebay_queries = get_ebay_queries_for_dept(keyword, dept)
    logger.info(f"  🌎 eBay Queries: {ebay_queries[:3]}")
    update_heartbeat(f"🔎 [{dept_name}] {keyword}")

    seen_ids = load_seen_ids()
    new_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36", locale="ja-JP")
            page = context.new_page()

            for q in ebay_queries[:5]:
                if sourcing_budget_exhausted():
                    break
                # 本番用の価格・成約数取得
                velocity = get_sold_velocity(q, days=7)
                market_price_usd = get_market_price(q) or 0
                ebay_ref_desc = q

                if velocity == 0:
                    med, ref_desc = resolve_reference_sold_price_usd(
                        q,
                        similar_sold_queries,
                        days_wide=days_wide,
                        days_similar=days_similar,
                        min_samples=min_sold_samples,
                        max_entries=80,
                    )
                    if med is None:
                        logger.info(f"  ⏭️ スキップ（7d Soldなし・類似でもSold件数不足）: {q}")
                        continue
                    market_price_usd = med
                    ebay_ref_desc = ref_desc
                    logger.info(f"  📎 類似/広域Sold中央値で相場採用: {ref_desc} → ${med:.0f}")
                elif market_price_usd < min_sell_usd:
                    med, ref_desc = resolve_reference_sold_price_usd(
                        q,
                        similar_sold_queries,
                        days_wide=days_wide,
                        days_similar=days_similar,
                        min_samples=min_sold_samples,
                        max_entries=80,
                    )
                    if med is not None and med >= min_sell_usd:
                        market_price_usd = med
                        ebay_ref_desc = ref_desc
                        logger.info(f"  📎 アクティブ相場が低いためSold参照に切替: {ref_desc} → ${med:.0f}")
                    else:
                        logger.info(f"  ⏭️ スキップ（相場${market_price_usd:.0f} < ${min_sell_usd}・類似でも不足）: {q}")
                        continue

                if market_price_usd < min_sell_usd:
                    logger.info(f"  ⏭️ スキップ（相場${market_price_usd:.0f} < ${min_sell_usd}）: {q}")
                    continue
                logger.info(
                    f"  💎 ターゲット: {q} (7d Sold:{velocity}, 採用相場:${market_price_usd:.0f}) 参照:{ebay_ref_desc}"
                )

                mercari_q = keyword
                url = f"https://jp.mercari.com/search?keyword={mercari_q}&status=on_sale&sort=created_time&order=desc&item_trading_format=1"

                try:
                    items = get_mercari_items_with_retry(page, url)
                    time.sleep(random.uniform(3, 7))  # Randomized delay to avoid rate limiting

                    for item in items:
                        if sourcing_budget_exhausted():
                            break
                        if not item["id"] or item["id"] in seen_ids or new_count >= max_per_kw:
                            continue

                        title_lower = (item.get("title", "") + " " + keyword).lower()

                        # ========== オークション除外（最優先・経営破綻防止） ==========
                        # タイトルベースの即時フィルタ（説明文の「入札」で誤爆しないようタイトルのみ）
                        if any(kw in title_lower for kw in ["オークション", "auction"]):
                            logger.info(f"  ⛔ オークション除外(タイトル): {item.get('title', '')[:40]}")
                            seen_ids.add(item["id"])
                            continue
                        # mercari_checkerでAPIレベルのオークション判定
                        try:
                            mc_result = check_mercari_status(item["url"], delay=1.0)
                            mc_status = mc_result.get("status", "")
                            if mc_status == "auction":
                                logger.warning(f"  ⛔ オークション除外(API): {item.get('title', '')[:40]}")
                                seen_ids.add(item["id"])
                                continue
                            if mc_status in ("sold_out", "deleted"):
                                logger.info(f"  ⏭️ 売切/削除済み: {item.get('title', '')[:40]}")
                                seen_ids.add(item["id"])
                                continue
                        except Exception as mc_err:
                            logger.warning(f"  ⚠️ メルカリチェック失敗（安全のためスキップ）: {mc_err}")
                            continue
                        # ==============================================================

                        # 部署NGキーワードフィルタ（他部署の商品を弾く）
                        if dept_ng and any(ng in title_lower for ng in dept_ng):
                            continue

                        # 部署のcard_keywordsで該当カテゴリか判定（あれば優先、なければ従来JP_CARD_KEYWORDS）
                        filter_keywords = dept_card_kw if dept_card_kw else JP_CARD_KEYWORDS
                        if not any(kw in title_lower for kw in filter_keywords):
                            continue

                        # 共通NGフィルタ
                        if any(ng in title_lower for ng in NG_KEYWORDS):
                            continue

                        m_price = item["price"]
                        # 部署別の価格範囲チェック
                        if m_price > dept_max_price or m_price < dept_min_price:
                            continue

                        # 商品タイトルで個別にeBay相場を取得
                        item_en = translate_to_english(item.get("title", ""))
                        item_market = get_market_price(item_en) if item_en else None
                        ck = [str(c).lower() for c in (dept.get("card_keywords") or [])] if dept else []
                        if (not item_market or item_market <= 0) and "bbm" in ck:
                            for y in re.findall(r"(20[0-2]\d|19\d{2})", item.get("title", "") or "")[:2]:
                                item_market = median_sold_price_usd(
                                    f"Shohei Ohtani BBM {y}",
                                    days=days_similar,
                                    min_samples=min_sold_samples,
                                )
                                if item_market:
                                    break
                            if not item_market or item_market <= 0:
                                for sq in similar_sold_queries[:5]:
                                    item_market = median_sold_price_usd(
                                        sq, days=days_similar, min_samples=min_sold_samples
                                    )
                                    if item_market:
                                        break
                        # 個別相場が取れた場合はそちらを使用、取れない場合はキーワード相場を使用
                        actual_market = item_market if item_market and item_market > 0 else market_price_usd
                        sell_price_usd = calculate_competitive_price(actual_market, dept)
                        potential_profit = calc_profit(sell_price_usd, m_price)
                        roi = potential_profit / m_price * 100 if m_price > 0 else 0

                        if potential_profit >= profit_threshold and roi >= 25:
                            basis = (
                                f"[{dept_name}] eBay参照:{ebay_ref_desc} | 個別相場:${actual_market:.1f} "
                                f"→ 出品:${sell_price_usd:.1f} / 利益:¥{int(potential_profit):,} / ROI:{roi:.0f}%"
                            )
                            if append_to_auto_sheet(item["url"], int(potential_profit), item["title"], m_price, basis):
                                _SOURCING_RUN["added"] += 1
                            seen_ids.add(item["id"])
                            new_count += 1
                            time.sleep(random.uniform(1, 3))
                    if sourcing_budget_exhausted():
                        break
                except Exception as e:
                    logger.error(f"Scrape Final Error: {e}")
                    continue
                if sourcing_budget_exhausted():
                    break
        finally:
            browser.close()
    update_heartbeat(f"✅ [{dept_name}] Sourcing Complete")
    save_seen_ids(seen_ids)

if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser(description="Mercari reverse sourcing → 自動出品シート")
    _ap.add_argument("--dept", metavar="DIR", help="sourcing 配下の部署フォルダ名のみ実行（例: ohtani）")
    _ap.add_argument("--max-additions", type=int, metavar="N", help="この実行でシートに追加する行の上限")
    _cli = _ap.parse_args()
    if _cli.max_additions is not None:
        _SOURCING_RUN["max_additions"] = max(0, _cli.max_additions)
        _SOURCING_RUN["added"] = 0
        logger.info(f"📊 シート追加上限: {_SOURCING_RUN['max_additions']}件/実行")

    # ── Phase 1: 部署別キーワード（sourcing/*/keywords.json）──
    departments = load_department_keywords()
    if _cli.dept:
        departments = [d for d in departments if os.path.basename(d.get("_dir", "")) == _cli.dept or d.get("department") == _cli.dept]
        if not departments:
            logger.error(f"📂 --dept {_cli.dept!r} に一致する sourcing/*/keywords.json がありません")
        else:
            logger.info(f"🏢 --dept {_cli.dept}: {len(departments)}部署のみ実行")
    if departments:
        logger.info(f"🏢 {len(departments)}部署のキーワードを自動リサーチ開始")
        for dept in departments:
            dept_name = dept.get("department", "不明")
            mercari_kws = dept.get("mercari_keywords", [])
            logger.info(f"━━━ {dept_name}（{len(mercari_kws)}キーワード）━━━")
            for kw in mercari_kws:
                try:
                    scrape_and_source(kw, dept=dept)
                except Exception as e:
                    logger.error(f"[{dept_name}] Error on '{kw}': {e}")
    elif _cli.dept:
        logger.info("📂 Phase1 スキップ（--dept に一致する部署なし）")
    else:
        logger.info("📂 sourcing/ に部署キーワードが見つかりません。スプレッドシートのみ使用します。")

    # ── Phase 2: スプレッドシートのキーワード（従来互換）──
    # --dept 指定時は混在防止のため Phase2 しない
    if not _cli.dept:
        try:
            service = _get_service()
            res = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range="検索キーワード!A2:A50").execute()
            keywords = [r[0] for r in res.get("values", []) if r]
            if keywords:
                logger.info(f"📋 スプレッドシートから {len(keywords)}件のキーワードを追加リサーチ")
                for kw in keywords:
                    scrape_and_source(kw)
        except Exception as e:
            logger.error(f"Spreadsheet Keywords Error: {e}")
    else:
        logger.info("📋 Phase2（検索キーワードシート）は --dept 指定のためスキップ")

    logger.info("🏁 全リサーチ完了")
