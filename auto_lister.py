#!/usr/bin/env python3
"""
auto_lister.py — Phase 14: Profit-Driven Command Cockpit
【特長】
1. メルカリURL(A) と 期待利益(B) を読み取り、eBay価格(C)を自動算出
2. 優先出品（PRIORITY）→ 自動出品（AUTO）の2系統ループ
3. 00:00 自動クリア（Cockpit CLEAN）
"""

import sys
import json
import logging
import time
import requests
import xml.etree.ElementTree as ET
import fcntl
from datetime import datetime
from typing import Optional
import google.generativeai as genai
from playwright.sync_api import sync_playwright

from config import (
    GEMINI_API_KEY, GOOGLE_CREDENTIALS_PATH, SPREADSHEET_ID, SHEET_NAME,
    EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID, EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV,
    PRIORITY_SHEET_NAME, AUTO_SHEET_NAME, AUTO_SHEETS,
    EXCHANGE_RATE, SHIPPING_COST_JPY,
    SHIPPING_POLICY_MAP, SHIPPING_POLICY_DEFAULT,
    SLACK_WEBHOOK_URL
)
from sheets_manager import (
    _get_service, read_all_items, read_active_items, 
    update_item_status, append_item_to_inventory, 
    create_sheet_if_not_exists, clear_sheet_v2
)
from mercari_scraper import scrape_mercari_item
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
DEFAULT_PROMOTED_RATE = 0.03 # Promoted Listings率
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


def get_shipping_policy_id(item_price_usd: float) -> str:
    """商品価格($)に対応するeBayシッピングポリシーIDを返す"""
    if item_price_usd < 100:
        bracket = 0
    else:
        bracket = int((item_price_usd - 100) // 50) * 50 + 100
    # マップにあれば返す。なければ最も近い下のブラケットを探す
    if bracket in SHIPPING_POLICY_MAP:
        return SHIPPING_POLICY_MAP[bracket]
    lower_brackets = [k for k in SHIPPING_POLICY_MAP if k <= bracket]
    if lower_brackets:
        return SHIPPING_POLICY_MAP[max(lower_brackets)]
    return SHIPPING_POLICY_DEFAULT

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
            score = sum(1 for kw in card_kw if kw in text)
            if score > best_score:
                best_score = score
                best_dept = dept
        except:
            continue
    return best_dept


def ai_analyze(title_ja: str, desc_ja: str, dept: Optional[dict] = None) -> dict:
    """Geminiを使用してタイトルと説明文をSEO最適化する（部署特化プロンプト対応）"""
    # 部署が未指定なら自動判定
    if dept is None:
        dept = detect_department(title_ja, desc_ja)

    # 部署特化のヒント
    dept_hint = ""
    if dept:
        dept_hint = f"\n\nSPECIALIST CONTEXT: {dept.get('ai_prompt_hint', '')}"
        if dept.get("default_item_specifics"):
            dept_hint += f"\nDefault item_specifics to include: {json.dumps(dept['default_item_specifics'])}"
        if dept.get("ebay_category_id"):
            dept_hint += f"\nPreferred category_id: {dept['ebay_category_id']}"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [{
                "text": (
                    "You are an eBay listing SEO expert for Japanese collectibles.\n"
                    "Given this Japanese product info, create an optimized English eBay listing.\n"
                    "CRITICAL: Never include any external URLs, website addresses, or hyperlinks in the description. No http/https links, no brand websites, no reference pages. eBay prohibits all external links.\n"
                    f"Title: {title_ja}\nDescription: {desc_ja}\n\n"
                    "Return ONLY valid JSON with these keys:\n"
                    '- "title": English SEO title (max 80 chars, keywords front-loaded)\n'
                    '- "description_html": HTML product description (NO external URLs/links)\n'
                    '- "category_id": eBay category ID (e.g. "183454" for CCG cards)\n'
                    '- "item_specifics": object with relevant eBay item specifics\n'
                    + dept_hint
                )
            }]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2
        }
    }

    if not gemini_breaker.can_proceed():
        logger.warning(f"[Gemini] Circuit breaker OPEN — skipping AI analysis")
        return {}

    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                result = json.loads(text)
                gemini_breaker.record_success()
                return sanitize_ai_output(result)
            elif resp.status_code == 429:
                logger.warning(f"AI Rate Limit (Attempt {attempt+1}/3). Waiting...")
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
]


def sanitize_ai_output(ai_data: dict) -> dict:
    """Gemini AI出力をeBayポリシー準拠にサニタイズする"""
    import re as _re

    # 1. タイトル: 禁止ワード除去 & 80文字制限
    title = ai_data.get("title", "")
    for banned in EBAY_TITLE_BANNED_WORDS:
        title = _re.sub(r'\b' + banned + r'\b', '', title, flags=_re.IGNORECASE)
    title = _re.sub(r'\s+', ' ', title).strip()[:80]
    ai_data["title"] = title

    # 2. 商品説明: 危険なHTML・外部URL・禁止ワードを完全除去
    desc = ai_data.get("description_html", "")
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
    # 連続空白・改行の整理
    desc = _re.sub(r'\n{3,}', '\n\n', desc)
    desc = _re.sub(r'  +', ' ', desc)
    ai_data["description_html"] = desc.strip()

    # 3. Item Specifics: Condition系除去（XMLで指定するため二重指定防止）
    specs = ai_data.get("item_specifics", {})
    for drop in ["Condition", "condition", "Card Condition"]:
        specs.pop(drop, None)
    ai_data["item_specifics"] = specs

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
    title = kwargs.get("title", "")[:80]
    desc = kwargs.get("desc_html", "")
    price = kwargs.get("price_usd", 0)
    cat_id = kwargs.get("category_id", "183454")
    if cat_id not in VALID_CATEGORIES:
        cat_id = "183454"  # デフォルト: CCG Individual Cards
    policy_id = kwargs.get("shipping_policy_id", SHIPPING_POLICY_DEFAULT)
    pics = "".join([f"<PictureURL>{u}</PictureURL>" for u in kwargs.get("image_urls", [])])
    specs = kwargs.get("item_specifics", {})
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
    # Condition設定（カテゴリ別）
    condition_desc_xml = ""
    force_cond = kwargs.get("_force_condition")
    if force_cond:
        condition_id = force_cond
    elif cat_id in ("183454", "261328"):
        condition_id = "4000"
        condition_desc_xml = """
    <ConditionDescriptors>
      <ConditionDescriptor>
        <Name>40001</Name>
        <Value>400010</Value>
      </ConditionDescriptor>
    </ConditionDescriptors>"""
    elif cat_id == "183455":
        condition_id = "1000"
    else:
        condition_id = "3000"
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<AddFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <Item>
    <Title><![CDATA[{title}]]></Title>
    <Description><![CDATA[{desc}]]></Description>
    <PrimaryCategory><CategoryID>{cat_id}</CategoryID></PrimaryCategory>
    <StartPrice currencyID="USD">{price}</StartPrice>
    <ConditionID>{condition_id}</ConditionID>{condition_desc_xml}
    <Country>JP</Country>
    <Location>Japan</Location>
    <Currency>USD</Currency>
    <ListingDuration>GTC</ListingDuration>
    <ListingType>FixedPriceItem</ListingType>
    <Quantity>1</Quantity>
    <OutOfStockControl>true</OutOfStockControl>
    <SKU><![CDATA[{kwargs.get("mercari_url", "")}]]></SKU>
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
        resp = requests.post(EBAY_ENDPOINT, headers=headers, data=xml.encode("utf-8"), timeout=30)
        root = ET.fromstring(resp.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
        ack = root.find("ns:Ack", ns).text
        item_id_node = root.find(".//ns:ItemID", ns)
        # ItemIDが返っていれば出品成功（Warning付きでも）
        if item_id_node is not None and item_id_node.text:
            ebay_breaker.record_success()
            return {"success": True, "item_id": item_id_node.text}
        if ack in ("Success", "Warning"):
            ebay_breaker.record_success()
            return {"success": True, "item_id": item_id_node.text if item_id_node is not None else ""}
        errs = [e.text for e in root.findall(".//ns:LongMessage", ns)]
        errs_lower = " ".join(e.lower() for e in errs)
        logger.warning(f"  ❌ 出品失敗詳細: {' / '.join(errs)}")
        retry_count = kwargs.get("_retry_count", 0)
        if retry_count >= 3:
            return {"success": False, "errors": errs}
        kwargs["_retry_count"] = retry_count + 1

        # シッピングポリシーエラー → デフォルトに変更
        if ("shipping" in errs_lower or "profile" in errs_lower) and policy_id != SHIPPING_POLICY_DEFAULT:
            kwargs["shipping_policy_id"] = SHIPPING_POLICY_DEFAULT
            return add_item_to_ebay(**kwargs)

        # Conditionエラー → Used(3000)にフォールバック
        if "condition" in errs_lower and ("invalid" in errs_lower or "not valid" in errs_lower):
            logger.warning("  🔄 Condition変更 → Used(3000)でリトライ")
            kwargs["_force_condition"] = "3000"
            return add_item_to_ebay(**kwargs)

        # ポリシー違反（improper words）→ タイトル・説明文を安全版に差替え
        if "improper" in errs_lower or "violation" in errs_lower:
            import re as _re2
            logger.warning("  🔄 ポリシー違反 → タイトル・説明文を安全版でリトライ")
            clean_title = _re2.sub(r'[^\w\s\-/.,()#]', '', kwargs.get("title", "")).strip()[:80]
            kwargs["title"] = clean_title
            kwargs["desc_html"] = "<p>Authentic Japanese collectible. Ships from Japan worldwide with tracking.</p><p>Please see photos for condition details.</p>"
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
        resp = requests.post(EBAY_ENDPOINT, headers=headers, data=xml.encode("utf-8"), timeout=15)
        root = ET.fromstring(resp.text)
        ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
        ack = root.find("ns:Ack", ns)
        if ack is not None and ack.text in ("Success", "Warning"):
            return {"valid": True}
        errs = [e.text for e in root.findall(".//ns:LongMessage", ns)]
        return {"valid": False, "errors": errs}
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
    lock_file = open('/tmp/auto_lister.lock', 'w')
    try: fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except: return

    backup_critical_files()

    logger.info("🚀 Profit-Driven Command Cockpit Start")

    # === test_rules.py ゲート（絶対ルール） ===
    import subprocess
    _test_result = subprocess.run(
        [sys.executable, _os_mod.path.join(_os_mod.path.dirname(_os_mod.path.abspath(__file__)), "test_rules.py")],
        capture_output=True, text=True, timeout=120
    )
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

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
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
                for item in items:
                    if is_priority_sheet:
                        if (
                            max_priority_success is not None
                            and priority_success_count >= max_priority_success
                        ):
                            logger.info(
                                f"⏹️ 優先出品は成功{max_priority_success}件に達したため {s_name} の残りをスキップ"
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
                    res = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"{s_name}!B{row_num}").execute()
                    profit_val = res.get("values", [["0"]])[0][0]
                    try: profit_jpy = int(str(profit_val).replace(",", "").replace("円", ""))
                    except: profit_jpy = 5000 # デフォルト

                    update_item_status(row_num, "⏳ 処理中", s_name)
                    scraped = None
                    for retry in range(3):
                        scraped = scrape_mercari_item(url, playwright_browser=browser)
                        if scraped.get("success"):
                            break
                        logger.warning(f"  スクレイプ失敗 (リトライ {retry+1}/3): {url}")
                        time.sleep(3 * (retry + 1))
                    if not scraped or not scraped.get("success"):
                        update_item_status(row_num, "❌ スクレイプ失敗(3回)", s_name); continue

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
                    # 層2: mercari_checker.pyのAPI判定（DOM解析を信用しない二重チェック）
                    try:
                        from mercari_checker import check_mercari_status as _mc_check
                        mc_result = _mc_check(url, delay=0.5)
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
                    # ============================================

                    # 価格計算（利益に従順）
                    mercari_price = int(scraped["price_jpy"])
                    if s_name != PRIORITY_SHEET_NAME and (mercari_price < 1000 or mercari_price > 250000):
                        update_item_status(row_num, "⚠️ 仕入価格範囲外", s_name); continue
                    price_usd = calculate_listing_price(mercari_price, profit_jpy)
                    # 最低$99、最高$2,499
                    price_usd = max(price_usd, 99.0)
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
                    if final_profit < min_profit_required:
                        update_item_status(row_num, f"⚠️ 利益不足 ¥{int(final_profit):,} (要¥{min_profit_required:,}+)", s_name); continue
                    logger.info(f"  💰 出品価格${price_usd} | 利益¥{int(final_profit):,} | ROI{roi:.0f}%")

                    # 部署自動判定（上で取得済み）
                    ai_data = ai_analyze(scraped["title"], scraped["description"], dept=detected_dept)
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
                    )
                    if not sv_result["approved"]:
                        reason = " / ".join(sv_result["violations"])
                        update_item_status(row_num, f"🚫 監視ブロック: {reason[:80]}", s_name)
                        fail_count += 1
                        continue

                    # === SUPERVISOR: 説明文の外部URLチェック ===
                    desc_check = validate_description(ai_data.get("description_html", ""))
                    if not desc_check["approved"]:
                        update_item_status(row_num, "🚫 説明文に外部URL検出", s_name)
                        fail_count += 1
                        continue

                    ebay_res = add_item_to_ebay(
                        mercari_url=url, title=ai_data.get("title", ""),
                        desc_html=ai_data.get("description_html", ""),
                        price_usd=price_usd, image_urls=eps_urls,
                        category_id=ai_data.get("category_id", "1345"),
                        item_specifics=ai_data.get("item_specifics", {}),
                        shipping_policy_id=get_shipping_policy_id(price_usd),
                        dept=detected_dept
                    )

                    if ebay_res["success"] and not dry_run:
                        item_id = ebay_res["item_id"]
                        logger.info(f"  ✅ 成功: {item_id}")
                        # C列に出品価格($)、D列にItemID、E列にStatus
                        try:
                            service.spreadsheets().values().update(
                                spreadsheetId=SPREADSHEET_ID, range=f"{s_name}!C{row_num}:E{row_num}",
                                valueInputOption="USER_ENTERED", body={"values": [[f"${price_usd}", item_id, "✅ 出品済み"]]}
                            ).execute()
                        except Exception as sheet_err:
                            logger.error(f"  ⚠️ Sheet更新失敗（手動復旧要）: url={url} item_id={item_id} price=${price_usd} error={sheet_err}")
                        try:
                            append_item_to_inventory(url, item_id)
                        except Exception as inv_err:
                            logger.error(f"  ⚠️ 在庫登録失敗（手動復旧要）: url={url} item_id={item_id} error={inv_err}")
                        master_urls.add(url)
                        success_count += 1
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
        notify_slack(f"出品完了: 成功{success_count}件 / 失敗{fail_count}件")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-success", type=int, metavar="N", help="この実行でeBay出品に成功したら打ち切る件数（全チャンネル合算）")
    parser.add_argument(
        "--max-priority-success",
        type=int,
        metavar="N",
        help="優先出品シートでの出品成功が N 件に達したら優先チャンネルを打ち切り",
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
