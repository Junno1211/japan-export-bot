#!/usr/bin/env python3
"""
auto_lister.py — Phase 14: Profit-Driven Command Cockpit
【特長】
1. メルカリURL(A) と 期待利益(B) を読み取り、eBay価格(C)を自動算出
2. 手動キュー（PRIORITY_SHEET_NAME）→ 自動出品（AUTO）の2系統ループ
3. 出品成功＋在庫管理表登録後はリサーチ用シートの行を削除（キューに残さない）
4. 00:00 自動クリア（Cockpit CLEAN・出品済み残骸の掃除）
"""

import sys
import json
import logging
import re
import time
import requests
import xml.etree.ElementTree as ET
import fcntl
from datetime import datetime
from typing import Optional, Dict
import google.generativeai as genai
from playwright.sync_api import sync_playwright

from config import (
    GEMINI_API_KEY, GOOGLE_CREDENTIALS_PATH, SPREADSHEET_ID, SHEET_NAME,
    EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID, EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV,
    PRIORITY_SHEET_NAME, AUTO_SHEET_NAME, AUTO_SHEETS,
    EXCHANGE_RATE, SHIPPING_COST_JPY,
    SLACK_WEBHOOK_URL,
    MIN_MERCARI_PURCHASE_JPY,
    AUTO_MAX_MERCARI_PURCHASE_JPY,
    PRIORITY_MAX_MERCARI_PURCHASE_JPY,
    MANUAL_LISTING_SKIP_PRICE_USD_GTE,
    MERCARI_SCRAPE_MAX_RETRIES,
    MERCARI_SCRAPE_RETRY_BASE_SEC,
)
from common_rules import (
    HANDLING_DAYS,
    PROMOTED_LISTINGS_RATE,
    SHIPPING_METHOD,
    TITLE_MAX_LENGTH,
)
from sheets_manager import (
    _get_service, read_all_items, read_active_items,
    update_item_status, append_item_to_inventory,
    create_sheet_if_not_exists, clear_sheet_v2,
    _a1_range,
)
from mercari_scraper import MercariPipelineStopped, scrape_mercari_item
from ebay_updater import EbayTradingRateLimited, get_item_status, trading_post
from mercari_proxy import playwright_launch_kwargs
from shipping_policy_select import select_shipping_policy, ShippingBandMismatchError
from ebay_lister import add_item, upload_picture_bytes
from heartbeat import update_heartbeat
from circuit_breaker import gemini_breaker, ebay_breaker, mercari_breaker
from supervisor import validate_listing, validate_description, validate_config_unchanged, _audit_log
import csv
import glob
import shutil
import os as _os_mod
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)
_GEMINI_MODEL = "gemini-1.5-flash"

EBAY_ENDPOINT = {
    "production": "https://api.ebay.com/ws/api.dll",
    "sandbox":    "https://api.sandbox.ebay.com/ws/api.dll"
}.get(EBAY_ENV, "https://api.ebay.com/ws/api.dll")

VALID_CATEGORIES = {"183454", "183455", "261328", "69528", "31387", "1345"}

# eBay トレカ単品系: ConditionID 3000(Used) は使えない（4000 アングレ / 2750 グレードのみ）
EBAY_CARD_SINGLE_CATEGORY_IDS = frozenset({"183454", "261328", "183050"})
# API 用 Card Condition 記述子は固定（eBay 拒否・切り替え失敗を減らす）。実物の状態は説明文で伝える。
EBAY_CARD_UNGRADED_DESCRIPTOR_VALUE = "400010"

# 説明文 Shipping 用（URL・ドル額は書かない）。Gemini プロンプトと improper フォールバックで揃える
LISTING_SHIPPING_NOTE_HTML = (
    f"<h2>Shipping</h2><p>Ships from Japan within <strong>{HANDLING_DAYS} business days</strong> of cleared payment. "
    f"Shipped via <strong>{SHIPPING_METHOD}</strong> with <strong>tracking</strong>—the tracking number is added on eBay when the label is created. "
    "International shipping may be billed through eBay’s program (e.g. SpeedPAK) for customs handling; the amount at checkout reflects your address.</p>"
)


def _ebay_sku_from_mercari_url(mercari_url: str) -> str:
    """
    eBay SKU は最大 50 文字。URL 全体が長い場合は /item/m… の商品 ID のみを使う。
    在庫管理は inventory_manager._mercari_url_from_sku が m+数字から URL を復元する。
    """
    u = (mercari_url or "").strip()
    m = re.search(r"/item/(m\d+)", u, re.I)
    if m:
        return m.group(1)[:50]
    return u[:50] if len(u) > 50 else u


def notify_slack(text: str) -> None:
    """Slack通知（シンプル1行）"""
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
    except Exception as e:
        logger.warning(f"Slack通知失敗: {e}")

# --- 利益計算 (利益計算シート「送料で関税を徴収」完全再現) ---
FVF_RATE = 0.1325          # Final Value Fee
INTL_FEE_RATE = 0.0135     # 海外手数料
PAYONEER_RATE = 0.02        # Payoneer手数料
DEFAULT_PROMOTED_RATE = PROMOTED_LISTINGS_RATE  # Promoted Listings率（common_rules と同一）
SALES_TAX_RATE = 0.10       # Sales Tax (10%)


def get_customs_shipping_usd(item_price_usd: float) -> float:
    """商品価格($)から関税徴収用の送料($)を算出（送料シート完全再現）
    計算式: 価格帯の上限 × 18%
    """
    CUSTOMS_RATE = 0.18
    if item_price_usd >= 2500:
        return 0
    if item_price_usd < 100:
        return 100 * CUSTOMS_RATE  # $18
    bracket_lower = int((item_price_usd - 100) // 50) * 50 + 100
    bracket_upper = bracket_lower + 49
    return bracket_upper * CUSTOMS_RATE


def calc_profit(item_price_usd: float, purchase_jpy: int, promoted_rate: float = DEFAULT_PROMOTED_RATE) -> float:
    """商品価格($)と仕入価格(¥)から還付込み利益(¥)を算出（シート列H再現）"""
    shipping_usd = get_customs_shipping_usd(item_price_usd)
    total_usd = item_price_usd + shipping_usd
    total_jpy = total_usd * EXCHANGE_RATE

    # J: 合計手数料 = eBay系手数料(税込ベース) + Payoneer手数料(残額ベース)
    ebay_fees = total_jpy * (1 + SALES_TAX_RATE) * (FVF_RATE + INTL_FEE_RATE + promoted_rate)
    payoneer_fee = (total_jpy - ebay_fees) * PAYONEER_RATE
    total_fee = ebay_fees + payoneer_fee

    # K: 送料合計 = 実送料(¥3,000) + 関税徴収分(送料$×為替)
    shipping_total_jpy = SHIPPING_COST_JPY + shipping_usd * EXCHANGE_RATE

    # F: 粗利 = 売上 - 仕入 - 手数料 - 送料
    gross_profit = total_jpy - purchase_jpy - total_fee - shipping_total_jpy

    # H: 還付込み利益 = 粗利 + 仕入還付 + 手数料還付(FVF+海外のみ)
    refund_purchase = purchase_jpy * (10 / 110)  # 税込仕入の消費税還付
    refund_fees = total_jpy * (FVF_RATE + INTL_FEE_RATE) * (1 + SALES_TAX_RATE) * (10 / 110)
    net_profit = gross_profit + refund_purchase + refund_fees

    return net_profit


def calculate_listing_price(mercari_jpy: int, expected_profit_jpy: int) -> float:
    """期待利益(円)からeBay商品価格($)を二分探索で逆算する"""
    lo, hi = 1.0, 5000.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if calc_profit(mid, mercari_jpy) < expected_profit_jpy:
            lo = mid
        else:
            hi = mid
    price = round((lo + hi) / 2, 2)
    return max(price, 99.0)  # 最低販売価格 $99


def detect_department(title: str, desc: str = "") -> Optional[dict]:
    """商品タイトル・説明文から該当する部署設定を自動判定する（最多マッチ部署を選択）"""
    import os as _os
    sourcing_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "sourcing")
    if not _os.path.isdir(sourcing_dir):
        return None
    text = (title + " " + desc).lower()
    best_dept = None
    best_score = 0
    for dept_name in _os.listdir(sourcing_dir):
        kw_file = _os.path.join(sourcing_dir, dept_name, "keywords.json")
        if not _os.path.exists(kw_file):
            continue
        try:
            with open(kw_file, "r", encoding="utf-8") as f:
                dept = json.load(f)
            card_kw = [w.lower() for w in dept.get("card_keywords", [])]
            # NGキーワードに該当したら即除外
            ng_kw = [w.lower() for w in dept.get("ng_keywords", [])]
            if any(ng in text for ng in ng_kw):
                continue
            # 部署専用: いずれかがテキストに無いと選ばない（BBM/PSA 等の汎用語だけで大谷部署に誤マッチしない）
            require_any = [w.lower() for w in dept.get("require_any") or []]
            if require_any and not any(r in text for r in require_any):
                continue
            score = sum(1 for kw in card_kw if kw in text)
            if score > best_score:
                best_score = score
                best_dept = dept
        except:
            continue
    return best_dept


# Gemini 出品文（プロンプト本体。部署の ai_prompt_hint / ebay_keywords が USER CONTENT に追記される）
_LISTING_AI_QUALITY_RULES_RAW = """
## ROLE
You are an expert eBay listing copywriter for Japanese collectibles and hobby items sold to US and international buyers. You optimize for eBay search (Cassini) and buyer trust, without inventing facts.

## OBJECTIVES (in order)
1) **Search**: Title and item_specifics help the right buyers find the listing (keywords they actually type).
2) **Accuracy**: Only facts supported by the Japanese source text (or the given Mercari condition line).
3) **Compliance**: eBay policies and no prohibited claims.

## USER CONTENT
Below you will receive a block labeled PRODUCT (Japanese title + description), optional Mercari condition, and optional SPECIALIST CONTEXT from our category rules. Treat PRODUCT as the only source of product facts unless SPECIALIST CONTEXT clarifies standard terminology.

## TITLE — search & demand (JSON field "title")
- Max **80 characters**. Use **natural US English**; **no keyword stuffing**, no repeated phrases, no ALL CAPS.
- **Front-load** the first ~35–40 characters with the strongest query terms: **what the item is** (character / player / franchise), **product type** (e.g. card, figure), **set or year** if in source, **Japanese / Japan** when the listing is Japan-market (true from source).
- If graded in source (PSA, BGS, etc.), include that **exactly as stated** (e.g. "PSA 10").
- **End the title** with a **short honest condition tag in square brackets** (no space before `[`). Choose tags that match the Mercari label when given, e.g. `[New]`, `[NM]`, `[LP]`, `[Good]`, `[READ]`, `[Acceptable]`. Tags are for **expectation alignment**, not hype.
- **Do not** put prices, shipping costs, "free shipping", phone, email, or URLs in the title.
- Follow SPECIALIST CONTEXT for must-use names (e.g. correct player/character). If NICHE SEARCH PHRASES appear, align the title with **1–3 phrases that truly match** the source—do not add unrelated popular terms.

## DESCRIPTION — clarity (JSON field "description_html")
- Help buyers **confirm** the item (set, number, language of card text if stated). Do **not** invent rarity, investment value, or guaranteed resale. Do not claim scarcity unless the Japanese text supports it with specifics.

## PRICING
- **Never** state dollar amounts, discounts, "best price", or fee details in title or description (eBay shows price separately).

## FACTS
- Extract **all verifiable** facts (names, numbers, years, sets, grades, serials, quantities, accessories) into English. If the Japanese text is thin, keep the description shorter.
- **Never** invent rarity, provenance, grades, or authenticity. Player/character: use **only** names clearly supported by the Japanese text. If unsure, use set/team/year without inventing a person.

## EBAY POLICY (critical)
- No external URLs, links, http(s), www., email, phone, social handles, or competitor marketplace names in the description.
- No medical/health claims, investment advice, or guaranteed future value.
- Avoid absolute authenticity guarantees; for grading, prefer neutral wording ("Graded PSA 10") when the source shows it.

## VOICE
- Professional, clear US English. Prefer concrete nouns over vague hype.

## CONDITION INTEGRITY (critical — reduces Item Not As Described)
When a Mercari condition label is provided, it is **authoritative** for how "nice" the item may sound overall.
- If the label is **傷や汚れあり**, **やや傷や汚れあり**, **全体的に状態が悪い**, or similar: you **must not** use **Like New**, **Mint**, **Near Mint**, **Gem Mint**, **NM**, **MINT**, or any wording that implies flawless or shelf-fresh condition. Describe **wear, scratches, stains, edge wear, clouding, dents, fading, or play wear** using plain English (you may use words **Scratch**, **Stain**, **Wear** where they apply). Put the **worst, most buyer-relevant defects first** in the Condition section so they cannot be missed.
- Align narrative with eBay-style used tiers **in prose only** (do not paste policy URLs): **Used - Good** = noticeable wear or marks but still functional / intact for the hobby; **Used - Acceptable** = heavy wear or obvious damage—still describe factually from the label and photos, do not invent damage beyond the label.
- If the label is stronger (e.g. 新品・未使用, 未使用に近い, 目立った傷や汚れなし), stay proportional—do not invent flaws, and do not oversell beyond the label.
- **PSA/BGS/CGC graded slabs**: condition language follows the grade/slab; do not contradict the slab with "Near Mint" raw-card hype unless the source clearly describes slab/case damage.

## DESCRIPTION_HTML — structure (use <h2> in this order; omit only if there is truly no content for that block)
1) <h2>Condition</h2> — **First body section.** Plain English tied to the Mercari label. Use a **<ul>** of concrete defect categories that apply (e.g. <li>Scratches: …</li>, <li>Stains: …</li>, <li>Wear: …</li>) or state clearly if the label indicates only light wear. If no Mercari label was given, say so and tell the buyer to rely on photos. Do not bury negatives in the last sentence.
2) <h2>✨ Product Highlights</h2> — <p> or short <ul>: rarity, set, character, gameplay/collectibility **only from the Japanese text**. Do **not** claim the item "looks mint" or "presents as new" unless the Mercari label supports it.
3) <h2>✅ Item Details</h2> — <ul><li>…</li></ul> for hard facts (year, edition, language, card #, parallel, quantity, accessories). Include a subheading inside this section: <h3>Appearance</h3> then <p>…</p> repeating or expanding **surface condition** (scratches, gloss loss, corner whitening, print lines, box crush, yellowing) so it is easy to find. Facts only from source text + Mercari label.
4) <h2>⚠️ Important</h2> — <p> stating this is a **pre-owned** (or new-in-box, if label says new) item sold as pictured, and that the buyer should **examine every photo** including crops before purchase. No fear-mongering; be factual.
5) <h2>What's Included</h2> — single vs set, accessories as implied by source (omit if fully obvious from title).
6) <h2>Shipping</h2> — one <p> including **all** of: (a) ships from Japan; (b) ships within <strong>10 business days</strong> of cleared payment; (c) <strong>FedEx</strong> with <strong>tracking</strong>, tracking uploaded on eBay when shipped; (d) one sentence that international shipping may be higher due to eBay cross-border programs (no dollar amounts, no URLs); (e) no guaranteed delivery date to door; (f) no http(s) or tracking links in the description.

## HTML rules
- Allowed: h2, h3, p, ul, li, strong, em, br (sparingly). No <a>, <img>, style, script, table.
- Do not paste raw Japanese; translate or omit.

## category_id and item_specifics
- "category_id": valid eBay category id string for the product type when known; use SPECIALIST preferred category if provided and consistent with the item.
- "item_specifics": object of eBay item specifics. Prefer **filter-friendly** fields buyers use (Year, Brand, Character, Card Number, etc.) **only when supported by the source**. Omit or leave empty when unknown—**do not guess**.

## OUTPUT
Return **only** valid JSON with keys: "title", "description_html", "category_id", "item_specifics" (object).
"""

_LISTING_AI_QUALITY_RULES = (
    _LISTING_AI_QUALITY_RULES_RAW.replace(
        "Max **80 characters**", f"Max **{TITLE_MAX_LENGTH} characters**"
    )
    .replace(
        "<strong>10 business days</strong>",
        f"<strong>{HANDLING_DAYS} business days</strong>",
    )
    .replace("(c) <strong>FedEx</strong>", f"(c) <strong>{SHIPPING_METHOD}</strong>")
)


def _cdata_safe(text: str, max_len: int = 980) -> str:
    s = (text or "").replace("]]>", "]] >")
    return s[:max_len]


def map_booster_box_condition_id(condition_ja: str) -> str:
    """183455 等: 新品表記のみ New(1000)、それ以外は Used(3000)。"""
    t = (condition_ja or "").strip()
    if not t:
        return "3000"
    if "未使用に近い" in t or "目立った" in t or "やや傷" in t or "傷や汚れ" in t or "全体的" in t:
        return "3000"
    if "新品" in t or "未使用" in t:
        return "1000"
    return "3000"


def ai_analyze(
    title_ja: str,
    desc_ja: str,
    dept: Optional[dict] = None,
    condition_ja: str = "",
) -> dict:
    """Geminiを使用してタイトルと説明文をSEO最適化する（部署特化プロンプト対応）"""
    title_ja = (title_ja or "")[:4000]
    desc_ja = (desc_ja or "")[:12000]

    # 部署が未指定なら自動判定
    if dept is None:
        dept = detect_department(title_ja, desc_ja)

    # 部署特化のヒント
    dept_hint = ""
    if dept:
        aph = dept.get("ai_prompt_hint") or ""
        if aph.strip():
            dept_hint = f"\n\nSPECIALIST CONTEXT (follow strictly for terminology and must-mention facts):\n{aph}"
        if dept.get("default_item_specifics"):
            dept_hint += f"\nDefault item_specifics to include: {json.dumps(dept['default_item_specifics'])}"
        if dept.get("ebay_category_id"):
            dept_hint += f"\nPreferred category_id: {dept['ebay_category_id']}"
        ekw = dept.get("ebay_keywords") or []
        if isinstance(ekw, list) and ekw:
            flat = [str(x).strip() for x in ekw[:16] if str(x).strip()]
            if flat:
                dept_hint += (
                    "\nNICHE SEARCH PHRASES (eBay US; weave 1–3 into the title only when they match the source):\n"
                    + ", ".join(flat)
                )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    cond_hint = ""
    if (condition_ja or "").strip():
        cond_hint = (
            f"\nMercari seller-stated condition label (authoritative; align title tag + Condition + Appearance; "
            f"never oversell vs this label):\n{condition_ja.strip()}\n"
        )
    user_block = (
        "--- USER CONTENT ---\n"
        f"PRODUCT (Japanese source text)\nTitle:\n{title_ja}\n\nDescription:\n{desc_ja}\n"
        + cond_hint
        + dept_hint
    )
    payload = {
        "contents": [{
            "parts": [{
                "text": _LISTING_AI_QUALITY_RULES.strip() + "\n\n" + user_block
            }]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.15,
            "topP": 0.85,
            "maxOutputTokens": 8192,
        },
    }

    if not gemini_breaker.can_proceed():
        logger.warning(f"[Gemini] Circuit breaker OPEN — skipping AI analysis")
        return {}

    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, timeout=90)
            if resp.status_code == 200:
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                result = json.loads(text)
                gemini_breaker.record_success()
                return sanitize_ai_output(result, (condition_ja or "").strip())
            elif resp.status_code == 429:
                logger.warning(
                    f"[Gemini] HTTP 429 Rate Limit (Attempt {attempt+1}/3). Waiting..."
                )
                gemini_breaker.record_failure()
                time.sleep(15 * (attempt + 1))
                continue
            else:
                logger.error(f"AI REST Error {resp.status_code}: {resp.text}")
                gemini_breaker.record_failure()
                break
        except Exception as e:
            logger.error(f"AI Exception: {e}")
            gemini_breaker.record_failure()
            break
    return {}


# eBayタイトル禁止ワード（ポリシー違反で即拒否される）
EBAY_TITLE_BANNED_WORDS = [
    "damaged", "broken", "junk", "defective", "fake", "replica", "counterfeit",
    "copy", "not authentic", "not genuine", "bootleg", "pirated", "unauthorized",
    "crack", "torn", "ripped",
]

# eBay説明文禁止ワード（improper wordsエラーの原因）
EBAY_DESC_BANNED_WORDS = [
    "fake", "replica", "counterfeit", "bootleg", "pirated", "unauthorized",
    "knock-off", "knockoff", "imitation", "not original", "not genuine",
    "damaged", "broken", "junk", "defective",
    "guaranteed authentic", "100% authentic",  # 保証系は問題になることがある
    "best price", "lowest price", "cheap", "discount", "sale", "clearance",
    "contact me", "email me", "call me", "whatsapp", "telegram", "line",
    "paypal", "venmo", "zelle", "cash app", "wire transfer", "western union",
    "investment opportunity", "great investment", "rare investment",
    "miracle", "cure", "treats disease", "fda approved",
]

# eBay が「improper words」になりやすい絵文字・記号を除去（タイトル・説明・Specifics 値）
_EMOJI_AND_SYMBOL_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E0-\U0001F1FF"
    r"\U0000FE00-\U0000FE0F\U0000200D]+",
    flags=re.UNICODE,
)


# 説明のセクション見出し用（本文の絵文字は除去対象だが、これらは残す）
_EMOJI_PROTECT_SEQ = (
    ("\u26a0\ufe0f", "__EBAYSEC_WARN__"),
    ("\u26a0", "__EBAYSEC_WARN__"),
    ("\u2705", "__EBAYSEC_OK__"),
    ("\u2728", "__EBAYSEC_HI__"),
)


def strip_listing_emoji(text: str) -> str:
    if not text:
        return ""
    s = str(text)
    for orig, token in _EMOJI_PROTECT_SEQ:
        s = s.replace(orig, token)
    s = _EMOJI_AND_SYMBOL_RE.sub("", s).strip()
    for orig, token in _EMOJI_PROTECT_SEQ:
        s = s.replace(token, orig)
    return s


def _mercari_label_implies_significant_wear(condition_ja: str) -> bool:
    """メルカリ中古〜難あり帯。過大な美品表現をタイトル・説明から落とすトリガ。"""
    t = (condition_ja or "").strip()
    if not t:
        return False
    if "やや傷" in t:
        return True
    if "傷や汚れあり" in t:
        return True
    if "ジャンク" in t:
        return True
    if "全体的" in t and ("悪" in t or "悪い" in t):
        return True
    if "状態が悪" in t or "状態の悪" in t:
        return True
    return False


def _scrub_overpositive_condition_copy(text: str, condition_ja: str) -> str:
    """傷あり系ラベル時、Like New / Near Mint 等が混入したモデル出力を弱める（/slab表記がある場合は Gem Mint 等は残す）。"""
    if not _mercari_label_implies_significant_wear(condition_ja):
        return (text or "").strip()
    s = str(text or "")
    slab = bool(re.search(r"\b(PSA|BGS|CGC|SGC)\s*\d", s, re.I))
    patterns = [
        r"\bLike[-\s]?New\b",
        r"\bNear\s*Mint\b",
        r"\bMint\s+Condition\b",
        r"\bExcellent\s+Condition\b",
        r"\bEUC\b",
    ]
    if not slab:
        patterns.extend([r"\bGem\s*Mint\b", r"\bMint\b"])
    for pat in patterns:
        s = re.sub(pat, "", s, flags=re.IGNORECASE)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def scrub_ebay_fragment(text: str) -> str:
    """Item Specifics 等の短文から禁止語を除去"""
    s = str(text or "")
    for banned in EBAY_DESC_BANNED_WORDS:
        s = re.sub(r"(?i)\b" + re.escape(banned) + r"\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def sanitize_item_specifics_values(specs: dict) -> dict:
    """eBay Item Specifics の各値から禁止語・絵文字を除去（improper words 対策）"""
    if not specs:
        return {}
    out = {}
    for k, v in specs.items():
        if isinstance(v, list):
            out[k] = [scrub_ebay_fragment(strip_listing_emoji(x)) for x in v if str(x).strip()]
        else:
            out[k] = scrub_ebay_fragment(strip_listing_emoji(v))
    return out


def latinish_title_fallback(title: str, max_len: int = TITLE_MAX_LENGTH) -> str:
    """improper 再試行用: 記号を減らし英数字中心に（空なら固定文言）"""
    t = strip_listing_emoji(title or "")
    for banned in EBAY_TITLE_BANNED_WORDS:
        t = re.sub(r"\b" + banned + r"\b", "", t, flags=re.IGNORECASE)
    buf = []
    for c in t:
        if ord(c) < 128 and (c.isalnum() or c in " -/.,()#&+'"):
            buf.append(c)
        elif c in "\n\t":
            buf.append(" ")
        elif c.isalnum():
            buf.append(c)
    s = re.sub(r"\s+", " ", "".join(buf)).strip()[:max_len]
    return s if s else "Japanese Collectible Card"


def sanitize_ai_output(ai_data: dict, condition_ja: str = "") -> dict:
    """Gemini AI出力をeBayポリシー準拠にサニタイズする"""
    import re as _re

    # 1. タイトル: 絵文字・禁止ワード除去 & TITLE_MAX_LENGTH 文字制限
    title = strip_listing_emoji(ai_data.get("title", ""))
    title = _scrub_overpositive_condition_copy(title, condition_ja)
    for banned in EBAY_TITLE_BANNED_WORDS:
        title = _re.sub(r'\b' + banned + r'\b', '', title, flags=_re.IGNORECASE)
    title = _re.sub(r'\s+', ' ', title).strip()[:TITLE_MAX_LENGTH]
    ai_data["title"] = title

    # 2. 商品説明: 危険なHTML・外部URL・禁止ワードを完全除去
    desc = strip_listing_emoji(ai_data.get("description_html", ""))
    # 危険なHTMLタグを完全除去（script, iframe, form, style, object, embed, applet）
    desc = _re.sub(r'<(script|iframe|form|style|object|embed|applet|link|meta)\b[^>]*>.*?</\1>', '', desc, flags=_re.IGNORECASE | _re.DOTALL)
    desc = _re.sub(r'<(script|iframe|form|style|object|embed|applet|link|meta|input|button)\b[^>]*/?\s*>', '', desc, flags=_re.IGNORECASE)
    # on*イベントハンドラ除去
    desc = _re.sub(r'\bon\w+\s*=\s*["\'][^"\']*["\']', '', desc, flags=_re.IGNORECASE)
    # 外部URL・リンク
    desc = _re.sub(r'https?://[^\s<>"\']+', '', desc)
    desc = _re.sub(r'\bwww\.[^\s<>"\']+', '', desc)
    desc = _re.sub(r'<a\b[^>]*>.*?</a>', '', desc, flags=_re.IGNORECASE | _re.DOTALL)
    desc = _re.sub(r'\bhref\s*=\s*["\'][^"\']*["\']', '', desc, flags=_re.IGNORECASE)
    # 競合・仕入先サイト名
    desc = _re.sub(r'(?i)mercari|メルカリ|rakuten|楽天|yahoo\s*auction|ヤフオク|amazon|ebay\.com|ebay\.co', '', desc)
    # 禁止ワード除去
    for banned in EBAY_DESC_BANNED_WORDS:
        desc = _re.sub(r'(?i)\b' + _re.escape(banned) + r'\b', '', desc)
    # 空のリスト項目・空段落を整理（読みやすさ）
    desc = _re.sub(r"<li>\s*</li>", "", desc, flags=_re.IGNORECASE)
    desc = _re.sub(r"<p>\s*</p>", "", desc, flags=_re.IGNORECASE)
    desc = _re.sub(r"(<br\s*/?>)\s*(</?(?:h2|h3|ul|p)\b)", r"\2", desc, flags=_re.IGNORECASE)
    # 感嘆符の連打を弱める
    desc = _re.sub(r"!{2,}", "!", desc)
    # 連続空白・改行の整理
    desc = _re.sub(r'\n{3,}', '\n\n', desc)
    desc = _re.sub(r'  +', ' ', desc)
    desc = _scrub_overpositive_condition_copy(desc, condition_ja)
    ai_data["description_html"] = desc.strip()

    # 3. Item Specifics: Condition系除去 + 値の禁止語・絵文字除去
    specs = ai_data.get("item_specifics", {})
    for drop in ["Condition", "condition", "Card Condition"]:
        specs.pop(drop, None)
    ai_data["item_specifics"] = sanitize_item_specifics_values(specs)

    return ai_data

def add_item_to_ebay(**kwargs) -> dict:
    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "AddFixedPriceItem",
        "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml",
    }
    # VALID_CATEGORIES is defined at module level
    title = kwargs.get("title", "")[:TITLE_MAX_LENGTH]
    desc = kwargs.get("desc_html", "")
    price = kwargs.get("price_usd", 0)
    cat_id = str(kwargs.get("category_id", "183454")).strip()
    if cat_id not in VALID_CATEGORIES:
        cat_id = "183454"  # デフォルト: CCG Individual Cards
    sel = select_shipping_policy(float(price))
    policy_id = sel.policy_id
    if kwargs.get("shipping_policy_id") not in (None, "", policy_id):
        raise ShippingBandMismatchError(
            f"shipping_policy_id は指定禁止（select_shipping_policy のみ）。"
            f" got={kwargs.get('shipping_policy_id')!r} expected={policy_id!r} price=${price}"
        )
    pics = "".join([f"<PictureURL>{u}</PictureURL>" for u in kwargs.get("image_urls", [])])
    specs = sanitize_item_specifics_values(kwargs.get("item_specifics") or {})
    # CCGカード系カテゴリは "Game" 必須 — 部署データがあればそちらを優先
    if cat_id in ("183454", "183455", "261328") and "Game" not in specs:
        dept = kwargs.get("dept")
        if dept and dept.get("game_name"):
            specs["Game"] = dept["game_name"]
        else:
            # 部署不明時はタイトルから推定
            title_lower = kwargs.get("title", "").lower()
            if "pokemon" in title_lower or "pikachu" in title_lower or "charizard" in title_lower:
                specs["Game"] = "Pokémon TCG"
            elif "ohtani" in title_lower or "baseball" in title_lower:
                specs["Game"] = "Baseball"
            elif "sumo" in title_lower or "wrestling" in title_lower:
                specs["Game"] = "Other Trading Card Games"
            else:
                specs["Game"] = "One Piece Card Game"
    # --- Item Specifics サニタイズ (eBay Commerce Taxonomy API準拠) ---
    import re as _re

    # eBayカテゴリ別のMULTI項目（複数値を<Value>タグで個別に送る）
    MULTI_VALUE_KEYS = {
        "Character", "Features", "Sport", "Team", "League",
        "Player/Athlete", "Signed By", "Attribute/MTG:Color",
        "Creature/Monster Type",
    }
    # eBayカテゴリ別のSINGLE項目（1値のみ。カンマがあれば最初の値だけ使う）
    # MULTI_VALUE_KEYS以外は全てSINGLE扱い

    # Condition はXMLで指定するのでSpecificsから除去（二重指定エラー防止）
    for drop_key in ["Condition", "condition", "Card Condition"]:
        specs.pop(drop_key, None)

    # Year Manufactured / Year → 4桁数値のみ
    for year_key in ["Year Manufactured", "Year"]:
        if year_key in specs:
            match = _re.search(r"(19|20)\d{2}", str(specs[year_key]))
            specs[year_key] = match.group(0) if match else ""

    # Sports Trading Cards (261328) では Game ではなく Sport が必須
    if cat_id == "261328":
        specs.pop("Game", None)
        if "Sport" not in specs:
            specs["Sport"] = "Baseball"

    # XML生成
    specs_xml_parts = []
    for k, v in specs.items():
        if not v:
            continue
        # 配列値の処理
        if isinstance(v, list):
            values = [str(x).strip() for x in v if str(x).strip()]
        elif "," in str(v):
            values = [x.strip() for x in str(v).split(",") if x.strip()]
        else:
            values = [str(v).strip()]

        # 65文字超の値は切り詰め
        values = [x[:65] for x in values if x]
        if not values:
            continue

        if k in MULTI_VALUE_KEYS:
            # MULTI: 複数<Value>タグで送る
            value_xml = "".join(f"<Value><![CDATA[{val}]]></Value>" for val in values)
        else:
            # SINGLE: 最初の値のみ
            value_xml = f"<Value><![CDATA[{values[0]}]]></Value>"

        specs_xml_parts.append(f"<NameValueList><Name><![CDATA[{k}]]></Name>{value_xml}</NameValueList>")

    specs_xml = "".join(specs_xml_parts)
    mercari_condition_ja = (kwargs.get("mercari_condition_ja") or "").strip()
    # Condition設定（カテゴリ別）— メルカリ「商品の状態」に追従
    condition_desc_xml = ""
    condition_description_xml = ""
    _cid = cat_id
    force_cond = kwargs.get("_force_condition")
    # トレカ単品系は 4000+記述子を最優先（if force_cond より先。リトライの 3000 で上書きされないようにする）
    if _cid in EBAY_CARD_SINGLE_CATEGORY_IDS:
        kwargs.pop("_force_condition", None)
        condition_id = "4000"
        cd_val = EBAY_CARD_UNGRADED_DESCRIPTOR_VALUE
        condition_desc_xml = f"""
    <ConditionDescriptors>
      <ConditionDescriptor>
        <Name>40001</Name>
        <Value>{cd_val}</Value>
      </ConditionDescriptor>
    </ConditionDescriptors>"""
        logger.info(
            "  📋 eBay card: 4000 + descriptor %s（詳細は説明文・Mercari: %s）",
            cd_val,
            mercari_condition_ja or "—",
        )
    elif force_cond:
        condition_id = str(force_cond).strip()
    elif _cid == "183455":
        condition_id = map_booster_box_condition_id(mercari_condition_ja)
        if condition_id == "3000" and mercari_condition_ja:
            condition_description_xml = f"""
    <ConditionDescription><![CDATA[{_cdata_safe("Source condition label: " + mercari_condition_ja)}]]></ConditionDescription>"""
    else:
        condition_id = "3000"
        if mercari_condition_ja:
            condition_description_xml = f"""
    <ConditionDescription><![CDATA[{_cdata_safe("Source condition label: " + mercari_condition_ja)}]]></ConditionDescription>"""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<AddFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <Item>
    <Title><![CDATA[{title}]]></Title>
    <Description><![CDATA[{desc}]]></Description>
    <PrimaryCategory><CategoryID>{_cid}</CategoryID></PrimaryCategory>
    <StartPrice currencyID="USD">{price}</StartPrice>
    <ConditionID>{condition_id}</ConditionID>{condition_desc_xml}{condition_description_xml}
    <Country>JP</Country>
    <Location>Japan</Location>
    <Currency>USD</Currency>
    <DispatchTimeMax>{HANDLING_DAYS}</DispatchTimeMax>
    <ListingDuration>GTC</ListingDuration>
    <ListingType>FixedPriceItem</ListingType>
    <Quantity>1</Quantity>
    <OutOfStockControl>true</OutOfStockControl>
    <SKU><![CDATA[{_ebay_sku_from_mercari_url(kwargs.get("mercari_url", ""))}]]></SKU>
    <ItemSpecifics>{specs_xml}</ItemSpecifics>
    <PictureDetails>{pics}</PictureDetails>
    <SellerProfiles>
      <SellerShippingProfile>
        <ShippingProfileID>{policy_id}</ShippingProfileID>
      </SellerShippingProfile>
      <SellerReturnProfile>
        <ReturnProfileName>Return Accepted,Seller,30 Days,Money Back,in#0</ReturnProfileName>
      </SellerReturnProfile>
      <SellerPaymentProfile>
        <PaymentProfileName>Payment</PaymentProfileName>
      </SellerPaymentProfile>
    </SellerProfiles>
  </Item>
</AddFixedPriceItemRequest>"""
    if not ebay_breaker.can_proceed():
        logger.warning(f"[eBay] Circuit breaker OPEN — skipping eBay listing")
        return {"success": False, "errors": ["eBay circuit breaker OPEN"]}

    try:
        resp = trading_post(
            EBAY_ENDPOINT,
            headers,
            xml.encode("utf-8"),
            "AddFixedPriceItem",
            timeout=30,
        )
        root = ET.fromstring(resp.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
        ack_el = root.find("ns:Ack", ns)
        ack = ack_el.text if ack_el is not None else ""
        item_id_node = root.find(".//ns:ItemID", ns)
        # Phase0: Ack + ItemID + GetItem で二系統一致したときのみ成功
        if item_id_node is not None and item_id_node.text and ack in ("Success", "Warning"):
            iid = (item_id_node.text or "").strip()
            gi = get_item_status(iid)
            if not gi.get("success"):
                time.sleep(2.0)
                gi = get_item_status(iid)
            if not gi.get("success"):
                logger.error(
                    "  [eBay Trading] Phase0: AddFixedPriceItem は ItemID を返したが GetItem 失敗 — 成功扱いしない"
                )
                ebay_breaker.record_failure()
                return {"success": False, "errors": ["get_item_confirm_failed"]}
            ebay_breaker.record_success()
            return {"success": True, "item_id": iid}
        if ack in ("Success", "Warning"):
            logger.error(
                "  [eBay Trading] Phase0: Ack は成功だが ItemID 欠落 — 成功扱いしない"
            )
            ebay_breaker.record_failure()
            return {"success": False, "errors": ["missing_item_id_after_success_ack"]}
        errs = [e.text for e in root.findall(".//ns:LongMessage", ns)]
        errs_lower = " ".join(e.lower() for e in errs)
        logger.warning(f"  ❌ 出品失敗詳細: {' / '.join(errs)}")

        # improper words は Item Specifics 緩和より先に処理（文言・Specifics 値の両方が原因になり得る）
        if "improper" in errs_lower:
            scrub = int(kwargs.get("_ebay_improper_scrub", 0) or 0)
            if scrub < 3:
                kwargs["_ebay_improper_scrub"] = scrub + 1
                if scrub == 0:
                    t = strip_listing_emoji(kwargs.get("title", ""))
                    for banned in EBAY_TITLE_BANNED_WORDS:
                        t = re.sub(r"\b" + banned + r"\b", "", t, flags=re.IGNORECASE)
                    t = re.sub(r"\s+", " ", t).strip()[:TITLE_MAX_LENGTH]
                    kwargs["title"] = t if t else "Japanese Collectible Card"
                    d = kwargs.get("desc_html", "")
                    d = strip_listing_emoji(d)
                    for banned in EBAY_DESC_BANNED_WORDS:
                        d = re.sub(r"(?i)\b" + re.escape(banned) + r"\b", "", d)
                    kwargs["desc_html"] = re.sub(r"\s+", " ", d).strip() or (
                        "<h2>Overview</h2><p>Japanese collectible item. See photos for details.</p>"
                        + LISTING_SHIPPING_NOTE_HTML
                    )
                    kwargs["item_specifics"] = sanitize_item_specifics_values(
                        kwargs.get("item_specifics") or {}
                    )
                elif scrub == 1:
                    kwargs["title"] = latinish_title_fallback(kwargs.get("title", ""))
                    kwargs["desc_html"] = (
                        "<h2>Overview</h2><p>Japanese trading card product. See photos.</p>"
                        "<h2>Condition</h2><p>See listing photos.</p>"
                        + LISTING_SHIPPING_NOTE_HTML
                    )
                    sp = kwargs.get("item_specifics") or {}
                    kwargs["item_specifics"] = sanitize_item_specifics_values(
                        {
                            k: sp[k]
                            for k in (
                                "Game",
                                "Sport",
                                "Country/Region of Manufacture",
                                "Language",
                                "Card Name",
                            )
                            if k in sp
                        }
                    )
                    kwargs["item_specifics"].setdefault("Country/Region of Manufacture", "Japan")
                    kwargs["item_specifics"].setdefault("Language", "Japanese")
                else:
                    _prev_sp = dict(kwargs.get("item_specifics") or {})
                    _game = _prev_sp.get("Game")
                    kwargs["title"] = "Japanese Trading Card Collectible"
                    kwargs["desc_html"] = (
                        "<p>Japanese collectible. Photos show the item. "
                        f"Ships from Japan within {HANDLING_DAYS} business days via {SHIPPING_METHOD} with tracking on eBay. "
                        "International shipping rate at checkout may include eBay program handling.</p>"
                    )
                    kwargs["item_specifics"] = {
                        "Country/Region of Manufacture": "Japan",
                        "Language": "Japanese",
                    }
                    if _game:
                        g = scrub_ebay_fragment(str(_game))
                        if g:
                            kwargs["item_specifics"]["Game"] = g[:60]
                logger.warning(
                    "  🔄 improper words → 安全化リトライ (pass %s/3)",
                    kwargs["_ebay_improper_scrub"],
                )
                return add_item_to_ebay(**kwargs)

        # Item Specifics 改名・eBay 推奨値 / 修正不可系 → specifics を段階的に削ってリトライ
        spec_relax = kwargs.get("_ebay_spec_relax", 0)
        if spec_relax < 3 and (
            "renamed" in errs_lower
            or "cannot be listed or modified" in errs_lower
            or "as per ebay" in errs_lower
        ):
            kwargs["_ebay_spec_relax"] = spec_relax + 1
            orig_specs = dict(kwargs.get("item_specifics", {}) or {})
            if spec_relax == 0:
                keep_keys = (
                    "Game", "Sport", "Country/Region of Manufacture", "Language", "Card Name",
                )
                kwargs["item_specifics"] = {
                    k: v for k, v in orig_specs.items() if k in keep_keys
                }
            elif spec_relax == 1:
                kwargs["item_specifics"] = {
                    "Country/Region of Manufacture": "Japan",
                    "Language": "Japanese",
                }
            else:
                kwargs["item_specifics"] = {}
            logger.warning(f"  🔄 eBay Item Specifics 緩和リトライ (stage {spec_relax + 1}/3)")
            return add_item_to_ebay(**kwargs)

        if "shipping" in errs_lower or "profile" in errs_lower:
            logger.error(
                "  ❌ eBay shipping/profile エラー — band 外のデフォルト差し替えは行わない: %s",
                " / ".join(errs),
            )
            return {"success": False, "errors": errs}

        retry_count = kwargs.get("_retry_count", 0)
        if retry_count >= 3:
            return {"success": False, "errors": errs}
        kwargs["_retry_count"] = retry_count + 1

        # Conditionエラー → Used(3000)（トレカ単品カテゴリ以外のみ）
        if (
            "condition" in errs_lower
            and ("invalid" in errs_lower or "not valid" in errs_lower)
            and _cid not in EBAY_CARD_SINGLE_CATEGORY_IDS
        ):
            logger.warning("  🔄 Condition変更 → Used(3000)でリトライ")
            kwargs["_force_condition"] = "3000"
            return add_item_to_ebay(**kwargs)

        # improper は上で最大3パス処理済み。violation のみ別メッセージのときだけ安全版へ
        if "violation" in errs_lower and "improper" not in errs_lower:
            import re as _re2
            logger.warning("  🔄 ポリシー violation → タイトル・説明文を安全版でリトライ")
            clean_title = _re2.sub(r"[^\w\s\-/.,()#]", "", kwargs.get("title", "")).strip()[:TITLE_MAX_LENGTH]
            kwargs["title"] = clean_title or "Japanese Collectible"
            kwargs["desc_html"] = (
                "<p>Authentic Japanese collectible. Please see photos for condition details.</p>"
                + LISTING_SHIPPING_NOTE_HTML
            )
            kwargs["item_specifics"] = sanitize_item_specifics_values(kwargs.get("item_specifics") or {})
            return add_item_to_ebay(**kwargs)

        # Item Specificsエラー → 必須項目のみに絞る
        if "item specifics" in errs_lower or "value of" in errs_lower or "is missing" in errs_lower:
            logger.warning("  🔄 Item Specifics → 最小構成でリトライ")
            orig_specs = kwargs.get("item_specifics", {})
            minimal_specs = {}
            for keep_key in ["Game", "Sport", "Country/Region of Manufacture", "Language"]:
                if keep_key in orig_specs:
                    minimal_specs[keep_key] = orig_specs[keep_key]
            minimal_specs.setdefault("Country/Region of Manufacture", "Japan")
            minimal_specs.setdefault("Language", "Japanese")
            kwargs["item_specifics"] = minimal_specs
            return add_item_to_ebay(**kwargs)

        return {"success": False, "errors": errs}
    except EbayTradingRateLimited as e:
        logger.error("  [eBay Trading] HTTP 429 — 処理停止（Phase 0）: %s", e)
        ebay_breaker.record_failure()
        try:
            from notifier import notify_slack

            notify_slack(f"🛑 **[eBay Trading] AddFixedPriceItem** 429 — {e}")
        except Exception:
            pass
        return {"success": False, "errors": [str(e)]}
    except Exception as e:
        ebay_breaker.record_failure()
        return {"success": False, "errors": [str(e)]}


def smart_cleanup(sheet_name: str):
    """出品済みの行だけを削除する"""
    service = _get_service()
    res = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"{sheet_name}!A:E").execute()
    rows = res.get("values", [])
    if not rows: return
    
    # 2行目以降（データ行）で「出品済み」のものを特定
    rows_to_keep = [rows[0]] # ヘッダーは保持
    for row in rows[1:]:
        # E列（インデックス4）がStatus
        status = row[4] if len(row) > 4 else ""
        if "出品済み" not in status:
            rows_to_keep.append(row)
            
    # シートを一旦クリアして、残すべき行だけを書き戻す
    service.spreadsheets().values().clear(spreadsheetId=SPREADSHEET_ID, range=f"{sheet_name}!A1:Z1000").execute()
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID, range=f"{sheet_name}!A1",
        valueInputOption="USER_ENTERED", body={"values": rows_to_keep}
    ).execute()
    logger.info(f"🧹 {sheet_name} の整理完了 (未処理品は保持)")

def check_ebay_token_health() -> dict:
    """eBayトークンの有効性を確認する"""
    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "GetUser",
        "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml",
    }
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<GetUserRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
</GetUserRequest>"""
    try:
        resp = trading_post(
            EBAY_ENDPOINT,
            headers,
            xml.encode("utf-8"),
            "GetUser_token_health",
            timeout=15,
        )
        root = ET.fromstring(resp.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
        ack = root.find("ns:Ack", ns)
        if ack is not None and ack.text in ("Success", "Warning"):
            return {"valid": True}
        errs = [e.text for e in root.findall(".//ns:LongMessage", ns)]
        return {"valid": False, "errors": errs}
    except EbayTradingRateLimited as e:
        return {"valid": False, "errors": [str(e)]}
    except Exception as e:
        return {"valid": False, "errors": [str(e)]}


def cleanup_old_logs():
    """7日以上前のログファイルを削除"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cutoff = time.time() - 7 * 86400
    deleted = 0
    for pattern in [os.path.join(base_dir, "*.log"), os.path.join(base_dir, "logs", "*.log")]:
        for f in glob.glob(pattern):
            try:
                if os.path.getmtime(f) < cutoff:
                    os.remove(f)
                    deleted += 1
            except:
                pass
    if deleted:
        logger.info(f"🧹 古いログ {deleted}件 削除")


def backup_critical_files():
    """重要ファイルのバックアップ（最新3世代保持）"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    backup_dir = os.path.join(base_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    critical_files = ["seen_ids.json", "items.csv", "processed_messages.json"]

    for fname in critical_files:
        src = os.path.join(base_dir, fname)
        if os.path.exists(src):
            dst = os.path.join(backup_dir, f"{fname}.{timestamp}")
            try:
                shutil.copy2(src, dst)
            except Exception as e:
                logger.warning(f"Backup failed for {fname}: {e}")

    # Keep only latest 3 backups per file
    for fname in critical_files:
        pattern = os.path.join(backup_dir, f"{fname}.*")
        backups = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        for old in backups[3:]:
            try:
                os.remove(old)
            except:
                pass

    logger.info(f"💾 バックアップ完了")


def run_auto_listing(
    dry_run: bool = False,
    max_success: int = None,
    max_priority_success: int = None,
    max_auto_success: int = None,
):
    lock_path = "/tmp/auto_lister.lock"
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        lock_file.close()
        msg = (
            f"⏳ auto_lister をスキップ: ロック取得できず（別実行中の可能性） "
            f"{lock_path}: {e}"
        )
        logger.warning(msg)
        try:
            notify_slack(msg[:300])
        except Exception:
            pass
        return

    backup_critical_files()

    logger.info("🚀 Profit-Driven Command Cockpit Start")

    # === test_rules.py ゲート（絶対ルール） ===
    # 既定120秒だと Google/メルカリが遅いと TimeoutExpired になるため長めにする（秒で上書き可）
    import subprocess
    _tr_timeout = int(os.environ.get("TEST_RULES_TIMEOUT_SEC", "600"))
    try:
        _test_result = subprocess.run(
            [sys.executable, _os_mod.path.join(_os_mod.path.dirname(_os_mod.path.abspath(__file__)), "test_rules.py")],
            capture_output=True, text=True, timeout=_tr_timeout,
        )
    except subprocess.TimeoutExpired:
        logger.error(
            f"🚨 test_rules.py が {_tr_timeout} 秒でタイムアウト — 出品中止（遅延時は TEST_RULES_TIMEOUT_SEC を増やす）"
        )
        notify_slack("🚨 test_rules.py タイムアウト — auto_lister 出品中止")
        return
    if _test_result.returncode != 0:
        logger.error(f"🚨 test_rules.py 失敗 — 出品中止")
        logger.error(_test_result.stdout[-500:] if _test_result.stdout else "no output")
        notify_slack("🚨 test_rules.py 失敗 — auto_lister 出品中止")
        return
    logger.info("✅ test_rules.py 全テスト合格")

    # === SUPERVISOR: 設定改ざんチェック ===
    config_check = validate_config_unchanged()
    if not config_check["approved"]:
        logger.error(f"[SUPERVISOR] 設定改ざん検出！起動中止: {config_check['violations']}")
        notify_slack(f"[SUPERVISOR] 設定改ざん検出！出品を全停止しました: {config_check['violations']}")
        return

    token_status = check_ebay_token_health()
    if not token_status["valid"]:
        logger.error(f"🚨 eBayトークン無効: {token_status.get('errors', [])}")
        notify_slack(f"🚨 eBayトークン無効！全出品停止中。トークン更新が必要です。エラー: {' / '.join(token_status.get('errors', []))[:200]}")
        return
    logger.info("✅ eBayトークン有効")
    create_sheet_if_not_exists(PRIORITY_SHEET_NAME)
    for _s in AUTO_SHEETS:
        create_sheet_if_not_exists(_s)

    # 00:00 定期クリーンアップ（出品済みのみ消去）
    if not dry_run and datetime.now().strftime("%H:%M") == "00:00":
        smart_cleanup(PRIORITY_SHEET_NAME)
        for _s in AUTO_SHEETS:
            smart_cleanup(_s)
        cleanup_old_logs()

    # 重複 = 同じURLで既にeBayに出品済み（ItemIDがある）もののみ
    master_items = read_all_items(SHEET_NAME)
    master_urls = {item["mercari_url"] for item in master_items
                   if item["mercari_url"] and item.get("ebay_item_id")}
    # items.csv に記録済みのURLも重複チェック対象に追加（単一の正規ソース）
    _items_csv_path = _os_mod.path.join(_os_mod.path.dirname(_os_mod.path.abspath(__file__)), "items.csv")
    if _os_mod.path.exists(_items_csv_path):
        try:
            with open(_items_csv_path, "r", encoding="utf-8") as _f:
                for _row in csv.DictReader(_f):
                    _csv_url = _row.get("mercari_url", "").strip()
                    if _csv_url:
                        master_urls.add(_csv_url)
            logger.info(f"items.csv URLを重複チェックに追加済み")
        except Exception as _csv_err:
            logger.warning(f"items.csv 読み込み失敗（スキップ）: {_csv_err}")
    logger.info(f"重複チェック対象URL数（出品済みのみ）: {len(master_urls)}")
    processed_urls = set()  # 同一実行内の重複防止
    service = _get_service()

    success_count = 0
    fail_count = 0
    priority_success_count = 0
    auto_success_count = 0
    success_by_department: Dict[str, int] = {}

    with sync_playwright() as p:
        _launch = dict(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        _launch.update(playwright_launch_kwargs())
        browser = p.chromium.launch(**_launch)
        try:
            listing_capped = False
            for s_name in [PRIORITY_SHEET_NAME, AUTO_SHEET_NAME] + AUTO_SHEETS:
                items = read_active_items(s_name)
                if not items:
                    continue

                is_priority_sheet = s_name == PRIORITY_SHEET_NAME
                if (
                    not is_priority_sheet
                    and max_auto_success is not None
                    and auto_success_count >= max_auto_success
                ):
                    logger.info(
                        f"⏹️ 自動出品は成功{max_auto_success}件に達したため {s_name} をスキップ"
                    )
                    continue

                logger.info(f"--- チャンネル開始: {s_name} ({len(items)}件) ---")
                # 行削除を挟むため、下の行から処理（行番号ズレ防止）
                items = sorted(items, key=lambda x: x["row"], reverse=True)
                for item in items:
                    if is_priority_sheet:
                        if (
                            max_priority_success is not None
                            and priority_success_count >= max_priority_success
                        ):
                            logger.info(
                                f"⏹️ {PRIORITY_SHEET_NAME} は成功{max_priority_success}件に達したため {s_name} の残りをスキップ"
                            )
                            break
                    else:
                        if (
                            max_auto_success is not None
                            and auto_success_count >= max_auto_success
                        ):
                            logger.info(
                                f"⏹️ 自動出品は成功{max_auto_success}件に達したため {s_name} の残りをスキップ"
                            )
                            break
                    if max_success is not None and success_count >= max_success:
                        logger.info(f"⏹️ 出品成功 {max_success}件に達したため終了")
                        listing_capped = True
                        break
                    # All APIs down check — abort the entire run
                    if (not gemini_breaker.can_proceed() and
                            not ebay_breaker.can_proceed() and
                            not mercari_breaker.can_proceed()):
                        logger.error("All APIs down, aborting run")
                        notify_slack("All APIs down, aborting run")
                        return

                    row_num, raw_url = item["row"], item["mercari_url"]
                    url = raw_url.strip()

                    if url in master_urls or url in processed_urls:
                        update_item_status(row_num, "⚠️ 重複", s_name); continue
                    processed_urls.add(url)

                    # B列から「期待利益」を読み取る
                    res = service.spreadsheets().values().get(
                        spreadsheetId=SPREADSHEET_ID, range=_a1_range(s_name, f"B{row_num}")
                    ).execute()
                    profit_val = res.get("values", [["0"]])[0][0]
                    try: profit_jpy = int(str(profit_val).replace(",", "").replace("円", ""))
                    except: profit_jpy = 5000 # デフォルト

                    update_item_status(row_num, "⏳ メルカリ取得中", s_name)
                    scraped = None
                    max_sc = MERCARI_SCRAPE_MAX_RETRIES
                    for retry in range(max_sc):
                        try:
                            scraped = scrape_mercari_item(
                                url,
                                playwright_browser=browser,
                                require_buy_button=(s_name != PRIORITY_SHEET_NAME),
                            )
                        except MercariPipelineStopped as mps:
                            logger.error("  メルカリ sourcing 停止（Phase0）: %s", mps)
                            try:
                                from notifier import notify_slack

                                notify_slack(
                                    f"🛑 **[Mercari] listing 停止** Phase0 rate limit\n{mps}\n{url[:200]}"
                                )
                            except Exception:
                                pass
                            update_item_status(
                                row_num,
                                "🛑 メルカリRL停止",
                                s_name,
                            )
                            return
                        if scraped.get("success"):
                            break
                        logger.warning(
                            f"  スクレイプ失敗 (リトライ {retry + 1}/{max_sc}): {url} — {scraped.get('error', '')}"
                        )
                        time.sleep(MERCARI_SCRAPE_RETRY_BASE_SEC * (retry + 1))
                    if not scraped or not scraped.get("success"):
                        err = (scraped or {}).get("error") or "不明"
                        err_one = err.replace("\n", " ").strip()[:100]
                        update_item_status(
                            row_num,
                            f"❌ スクレイプ失敗({max_sc}回): {err_one}",
                            s_name,
                        )
                        continue

                    # ========== 出品前メルカリ状態チェック（必須・3層防御） ==========
                    # 無在庫転売のため、仕入れ不可能な商品の出品は厳禁
                    # 違反→注文キャンセル→Defect→アカウント停止→ビジネス終了
                    #
                    # 層1: mercari_scraper.pyのDOM解析結果
                    mercari_status = scraped.get("status", "")
                    if mercari_status == "sold_out":
                        update_item_status(row_num, "⛔ 売り切れ", s_name)
                        logger.warning(f"  ⛔ 売り切れ商品を除外: {url}")
                        continue
                    if mercari_status == "auction":
                        update_item_status(row_num, "⛔ オークション除外(スクレイプ)", s_name)
                        logger.warning(f"  ⛔ オークション商品を除外(スクレイプ): {url}")
                        continue
                    if mercari_status not in ("active", ""):
                        update_item_status(row_num, f"⛔ 購入不可({mercari_status})", s_name)
                        logger.warning(f"  ⛔ 購入不可商品を除外: {url} (status={mercari_status})")
                        continue
                    #
                    # 層2: mercari_checker（自動キューのみ）。手動はユーザー選定のため二重チェックしない。
                    if s_name != PRIORITY_SHEET_NAME:
                        try:
                            from mercari_checker import check_mercari_status as _mc_check
                            mc_result = _mc_check(url, delay=0.5, playwright_browser=browser)
                            mc_status = mc_result.get("status", "")
                            if mc_status == "auction":
                                update_item_status(row_num, "⛔ オークション除外(API)", s_name)
                                logger.warning(f"  ⛔ オークション商品を除外(API): {url}")
                                continue
                            if mc_status in ("sold_out", "deleted"):
                                update_item_status(row_num, "⛔ 売切/削除(API)", s_name)
                                logger.warning(f"  ⛔ 売切/削除商品を除外(API): {url}")
                                continue
                        except Exception as mc_err:
                            logger.warning(f"  ⚠️ API二重チェック失敗（安全のためスキップ）: {mc_err}")
                            update_item_status(row_num, "⚠️ メルカリAPI確認失敗", s_name)
                            continue
                    else:
                        logger.info("  手動キュー: メルカリAPI二重チェックをスキップ（ユーザー選定）")
                    # ============================================

                    update_item_status(row_num, "⏳ 価格・利益を計算中", s_name)
                    # 価格計算（利益に従順）
                    mercari_price = int(scraped["price_jpy"])
                    # 「手動」タブはユーザー選定のためメルカリ仕入れ額の上下限チェックはしない
                    if s_name != PRIORITY_SHEET_NAME:
                        max_purchase = AUTO_MAX_MERCARI_PURCHASE_JPY
                        if mercari_price < MIN_MERCARI_PURCHASE_JPY or mercari_price > max_purchase:
                            update_item_status(
                                row_num,
                                f"⚠️ 仕入価格範囲外 (¥{MIN_MERCARI_PURCHASE_JPY:,}〜¥{max_purchase:,})",
                                s_name,
                            )
                            continue
                    price_usd = calculate_listing_price(mercari_price, profit_jpy)
                    # 最低$99、最高$2,499
                    price_usd = max(price_usd, 99.0)
                    # 手動のみ: $2499 以上は頭打ちせずスキップ（高額を安く売らない）
                    if s_name == PRIORITY_SHEET_NAME and price_usd >= float(
                        MANUAL_LISTING_SKIP_PRICE_USD_GTE
                    ):
                        update_item_status(
                            row_num,
                            f"⚠️ 手動: ${MANUAL_LISTING_SKIP_PRICE_USD_GTE}+ は出品不可 (計${price_usd:.2f})",
                            s_name,
                        )
                        continue
                    price_usd = min(price_usd, 2499.0)
                    # 最終利益・ROI検証（B列は価格逆算用。最低利益は部署keywordsの min_profit_jpy と共通ルールのみ）
                    final_profit = calc_profit(price_usd, mercari_price)
                    roi = final_profit / mercari_price * 100 if mercari_price > 0 else 0
                    detected_dept = detect_department(scraped["title"], scraped["description"])
                    min_profit_required = 3000
                    if detected_dept and detected_dept.get("min_profit_jpy") is not None:
                        min_profit_required = max(
                            min_profit_required, int(detected_dept["min_profit_jpy"])
                        )
                    if mercari_price >= 50000:
                        min_profit_required = max(min_profit_required, 5000)
                    if s_name != PRIORITY_SHEET_NAME and final_profit < min_profit_required:
                        update_item_status(row_num, f"⚠️ 利益不足 ¥{int(final_profit):,} (要¥{min_profit_required:,}+)", s_name); continue
                    logger.info(f"  💰 出品価格${price_usd} | 利益¥{int(final_profit):,} | ROI{roi:.0f}%")

                    update_item_status(row_num, "⏳ AIでタイトル・説明作成中", s_name)
                    # 部署自動判定（上で取得済み）
                    ai_data = ai_analyze(
                        scraped["title"],
                        scraped["description"],
                        dept=detected_dept,
                        condition_ja=scraped.get("condition_label_ja", ""),
                    )
                    if not ai_data:
                        update_item_status(row_num, "❌ AI分析失敗", s_name); continue

                    # 部署のdefault_item_specificsをマージ（AI出力が優先）
                    if detected_dept and detected_dept.get("default_item_specifics"):
                        merged_specs = dict(detected_dept["default_item_specifics"])
                        merged_specs.update(ai_data.get("item_specifics", {}))
                        ai_data["item_specifics"] = merged_specs

                    # 部署のebay_category_idを優先（AIが変なカテゴリを返した場合の保険）
                    if detected_dept and detected_dept.get("ebay_category_id"):
                        ai_cat = ai_data.get("category_id", "")
                        if ai_cat not in VALID_CATEGORIES:
                            ai_data["category_id"] = detected_dept["ebay_category_id"]

                    update_item_status(row_num, "⏳ 画像をeBayへ送信中", s_name)
                    eps_urls = []
                    for j, img in enumerate(scraped.get("image_bytes", [])[:12]):
                        eps = upload_picture_bytes(img["bytes"], filename=f"i_{j}.jpg")
                        if eps: eps_urls.append(eps)
                        time.sleep(0.2)

                    if not eps_urls:
                        update_item_status(row_num, "❌ 画像転送失敗", s_name); continue

                    # === SUPERVISOR: 出品前の最終検証 ===
                    sv_result = validate_listing(
                        mercari_url=url,
                        mercari_price_jpy=mercari_price,
                        ebay_price_usd=price_usd,
                        profit_jpy=final_profit,
                        roi_pct=roi,
                        title=ai_data.get("title", ""),
                        description_html=ai_data.get("description_html", ""),
                        is_priority=(s_name == PRIORITY_SHEET_NAME),
                        existing_urls=master_urls,
                        manual_sheet=(s_name == PRIORITY_SHEET_NAME),
                    )
                    if not sv_result["approved"]:
                        reason = " / ".join(sv_result["violations"])
                        update_item_status(row_num, f"🚫 監視ブロック: {reason[:TITLE_MAX_LENGTH]}", s_name)
                        fail_count += 1
                        continue

                    # === SUPERVISOR: 説明文の外部URLチェック ===
                    desc_check = validate_description(ai_data.get("description_html", ""))
                    if not desc_check["approved"]:
                        update_item_status(row_num, "🚫 説明文に外部URL検出", s_name)
                        fail_count += 1
                        continue

                    update_item_status(row_num, "⏳ eBayに出品中", s_name)
                    ebay_res = add_item_to_ebay(
                        mercari_url=url, title=ai_data.get("title", ""),
                        desc_html=ai_data.get("description_html", ""),
                        price_usd=price_usd, image_urls=eps_urls,
                        category_id=ai_data.get("category_id", "1345"),
                        item_specifics=ai_data.get("item_specifics", {}),
                        dept=detected_dept,
                        mercari_condition_ja=scraped.get("condition_label_ja", ""),
                    )

                    if ebay_res["success"] and not dry_run:
                        item_id = ebay_res["item_id"]
                        logger.info(f"  ✅ 成功: {item_id}")
                        inv_ok = False
                        try:
                            append_item_to_inventory(url, item_id)
                            inv_ok = True
                        except Exception as inv_err:
                            logger.error(f"  ⚠️ 在庫登録失敗（手動復旧要）: url={url} item_id={item_id} error={inv_err}")
                        # C=出品価格 D=eBay ItemID E=ステータス を必ず書く（成功がシート上で分かるようにする）
                        # 行は即削除しない。00:00 の smart_cleanup が「出品済み」行のみ掃除。
                        status_cell = "✅ 出品済み" if inv_ok else "⚠️在庫表未登録"
                        try:
                            service.spreadsheets().values().update(
                                spreadsheetId=SPREADSHEET_ID,
                                range=f"{s_name}!C{row_num}:E{row_num}",
                                valueInputOption="USER_ENTERED",
                                body={"values": [[f"${price_usd}", str(item_id), status_cell]]},
                            ).execute()
                            logger.info(f"  📝 {s_name} 行{row_num}: C〜E に価格・ItemID・{status_cell}")
                        except Exception as sheet_err:
                            logger.error(f"  ⚠️ 出品成功だがシート更新失敗（手動復旧要）: {sheet_err}")
                        master_urls.add(url)
                        success_count += 1
                        _dn = (detected_dept or {}).get("department")
                        _dl = str(_dn).strip() if _dn else "未分類"
                        success_by_department[_dl] = success_by_department.get(_dl, 0) + 1
                        if is_priority_sheet:
                            priority_success_count += 1
                        else:
                            auto_success_count += 1
                    elif not dry_run:
                        msg = " / ".join(ebay_res.get("errors", []))
                        logger.error(f"  ❌ 出品失敗詳細: {msg}")
                        update_item_status(row_num, f"❌ 出品失敗: {msg[:100]}", s_name)
                        fail_count += 1
                    else:
                        logger.info(f"  [DRY RUN] 成功想定: {url} (${price_usd})")
                if listing_capped:
                    break
        finally:
            browser.close()

    if not dry_run and (success_count or fail_count):
        notify_slack(
            f"出品完了: 成功{success_count}件 / 失敗{fail_count}件 "
            f"（手動・自動出品シートは C〜E に $・ItemID・ステータス。出品済み行は翌日0時頃にシートから削除）"
        )
        try:
            from listing_metrics import record_listing_session, write_daily_report_md

            record_listing_session(
                success_count,
                fail_count,
                success_by_department if success_count else None,
            )
            report_path, obs_report = write_daily_report_md()
            logger.info(f"日報を更新: {report_path}")
            if obs_report:
                logger.info(f"Obsidian Vault 日報: {obs_report}")
        except Exception as _met_err:
            logger.warning(f"listing_metrics 記録失敗: {_met_err}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-success", type=int, metavar="N", help="この実行でeBay出品に成功したら打ち切る件数（全チャンネル合算）")
    parser.add_argument(
        "--max-priority-success",
        type=int,
        metavar="N",
        help="手動キュー（PRIORITY_SHEET_NAME）での出品成功が N 件に達したらそのチャンネルを打ち切り",
    )
    parser.add_argument(
        "--max-auto-success",
        type=int,
        metavar="N",
        help="自動出品系シート（自動出品 + 自動出品_*）での成功合計が N 件に達したら自動チャンネルを打ち切り",
    )
    args = parser.parse_args()
    run_auto_listing(
        dry_run=args.dry_run,
        max_success=args.max_success,
        max_priority_success=args.max_priority_success,
        max_auto_success=args.max_auto_success,
    )
