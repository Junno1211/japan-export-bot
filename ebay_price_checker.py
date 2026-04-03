import time
import base64
import requests
import logging
import urllib.parse
from typing import Optional, List
from config import EBAY_APP_ID, EBAY_CERT_ID, EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

_OAUTH_TOKEN = None
_TOKEN_EXPIRY = 0

def get_oauth_token() -> Optional[str]:
    global _OAUTH_TOKEN, _TOKEN_EXPIRY
    if _OAUTH_TOKEN and time.time() < _TOKEN_EXPIRY:
        return _OAUTH_TOKEN
    url = "https://api.ebay.com/identity/v1/oauth2/token"
    auth_str = f"{EBAY_APP_ID}:{EBAY_CERT_ID}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {b64_auth}"}
    data = {"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"}
    try:
        resp = requests.post(url, headers=headers, data=data, timeout=10)
        if resp.status_code == 200:
            res_json = resp.json()
            _OAUTH_TOKEN = res_json.get("access_token")
            _TOKEN_EXPIRY = time.time() + int(res_json.get("expires_in", 3600)) - 60
            return _OAUTH_TOKEN
        return None
    except Exception as e:
        logger.warning(f"get_oauth_token failed: {e}")
        return None

def get_winning_titles(keyword: str, playwright_browser=None) -> List[str]:
    """
    eBayから成功事例（Winners）のタイトルを取得する。
    1. Sold API (findCompletedItems)
    2. Active Browse API (Top Results/Success Evidence)
    """
    # 1. Sold API (Terapeak Essence)
    titles = _get_winning_titles_via_api(keyword)
    if titles: return titles
    
    # 2. Active Browse API (Winning Blueprint Fallback)
    return _get_winning_titles_via_browse_api(keyword)

def _get_winning_titles_via_api(keyword: str) -> List[str]:
    url = f"https://svcs.ebay.com/services/search/FindingService/v1"
    params = {
        "OPERATION-NAME": "findCompletedItems", "SERVICE-VERSION": "1.13.0",
        "SECURITY-APPNAME": EBAY_APP_ID, "RESPONSE-DATA-FORMAT": "XML",
        "keywords": keyword, "itemFilter(0).name": "SoldItemsOnly",
        "itemFilter(0).value": "true", "paginationInput.entriesPerPage": "5"
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        if "errorMessage" in resp.text: return [] # Rate limit / Security error
        root = ET.fromstring(resp.text)
        ns = {'ns': 'http://www.ebay.com/marketplace/search/v1/services'}
        titles = [t.text for t in root.findall(".//ns:title", ns)]
        return list(set(titles))[:5]
    except Exception as e:
        logger.warning(f"get_winning_titles via API failed (keyword={keyword!r}): {e}")
        return []

def _get_winning_titles_via_browse_api(keyword: str) -> List[str]:
    """Browse APIで現在売れている（Best Match上位）のタイトルを取得"""
    token = get_oauth_token()
    if not token: return []
    q = urllib.parse.quote(keyword)
    url = f"https://api.ebay.com/buy/browse/v1/item_summary/search?q={q}&limit=5"
    headers = {"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            items = resp.json().get("itemSummaries", [])
            return [i.get("title", "") for i in items if i.get("title")]
        return []
    except Exception as e:
        logger.warning(f"get_winning_titles via Browse API failed (keyword={keyword!r}): {e}")
        return []

def search_competitor_item(english_keyword: str) -> dict:
    token = get_oauth_token()
    if not token: return {}
    q = urllib.parse.quote(english_keyword)
    url = f"https://api.ebay.com/buy/browse/v1/item_summary/search?q={q}&limit=1"
    headers = {"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        items = resp.json().get("itemSummaries", [])
        if not items: return {}
        item_id = items[0].get("itemId", "").split("|")[-1]
        endpoint = "https://api.ebay.com/ws/api.dll" if EBAY_ENV.upper() == "PRODUCTION" else "https://api.sandbox.ebay.com/ws/api.dll"
        xml = f'''<?xml version="1.0" encoding="utf-8"?><GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents"><RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials><ItemID>{item_id}</ItemID><DetailLevel>ReturnAll</DetailLevel><IncludeItemSpecifics>true</IncludeItemSpecifics></GetItemRequest>'''
        resp_trade = requests.post(endpoint, headers={"X-EBAY-API-CALL-NAME": "GetItem", "Content-Type": "text/xml"}, data=xml.encode("utf-8"), timeout=15)
        root = ET.fromstring(resp_trade.text); nsp = {'ebay': 'urn:ebay:apis:eBLBaseComponents'}
        cat_id = root.findtext(".//ebay:PrimaryCategory/ebay:CategoryID", namespaces=nsp)
        specifics = {nv.findtext("ebay:Name", nsp): nv.findtext("ebay:Value", nsp) for nv in root.findall(".//ebay:NameValueList", nsp)}
        return {"category_id": cat_id, "specifics": specifics}
    except Exception as e:
        logger.warning(f"search_competitor_item failed (keyword={english_keyword!r}): {e}")
        return {}

def get_sold_velocity(keyword: str, days: int = 7) -> int:
    """直近の成約数を取得。Browse API → Finding APIフォールバック"""
    # 1. Browse API: itemsShippedで売れた実績を確認
    token = get_oauth_token()
    if token:
        try:
            q = urllib.parse.quote(keyword)
            # SOLD filter for Browse API
            url = f"https://api.ebay.com/buy/browse/v1/item_summary/search?q={q}&limit=5&filter=buyingOptions:{{FIXED_PRICE}},conditionIds:{{1000|1500|2000|2500|3000|4000|5000}}"
            headers = {"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                total = data.get("total", 0)
                # 出品数が多い = 需要がある市場
                if total >= 5:
                    return total
        except Exception as e:
            logger.warning(f"get_sold_velocity Browse API failed (keyword={keyword!r}): {e}")

    # 2. Finding API フォールバック
    url = f"https://svcs.ebay.com/services/search/FindingService/v1"
    end_time_from = (time.time() - (days * 86400))
    time_str = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(end_time_from))
    params = {
        "OPERATION-NAME": "findCompletedItems", "SERVICE-VERSION": "1.13.0",
        "SECURITY-APPNAME": EBAY_APP_ID, "RESPONSE-DATA-FORMAT": "XML",
        "keywords": keyword, "itemFilter(0).name": "SoldItemsOnly",
        "itemFilter(0).value": "true",
        "itemFilter(1).name": "EndTimeFrom",
        "itemFilter(1).value": time_str,
        "paginationInput.entriesPerPage": "100"
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        if "errorMessage" in resp.text:
            return 0
        root = ET.fromstring(resp.text)
        ns = {'ns': 'http://www.ebay.com/marketplace/search/v1/services'}
        count_node = root.find(".//ns:paginationOutput/ns:totalEntries", ns)
        if count_node is not None and count_node.text:
            return int(count_node.text)
        return 0
    except Exception as e:
        logger.warning(f"get_sold_velocity Finding API failed (keyword={keyword!r}): {e}")
        return 0

def get_market_price(keyword: str) -> Optional[float]:
    """Browse APIで現在出品中の価格平均（上位5件）を取得。Finding API Rate Limit回避"""
    # 1. Browse API（Rate Limit別枠）
    token = get_oauth_token()
    if token:
        try:
            q = urllib.parse.quote(keyword)
            url = f"https://api.ebay.com/buy/browse/v1/item_summary/search?q={q}&limit=20&filter=price:[60..],priceCurrency:USD"
            headers = {"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                items = resp.json().get("itemSummaries", [])
                prices = []
                for item in items:
                    price_info = item.get("price", {})
                    if price_info.get("currency") == "USD" and price_info.get("value"):
                        prices.append(float(price_info["value"]))
                if prices:
                    # 保守的: 下位50%の中央値を採用（高額外れ値を排除）
                    prices.sort()
                    n = len(prices)
                    lower_half = prices[:max(n//2, 1)]
                    return sum(lower_half) / len(lower_half) if lower_half else None
        except Exception as e:
            logger.warning(f"get_market_price Browse API failed (keyword={keyword!r}): {e}")

    # 2. Finding API フォールバック
    url = f"https://svcs.ebay.com/services/search/FindingService/v1"
    params = {
        "OPERATION-NAME": "findCompletedItems", "SERVICE-VERSION": "1.13.0",
        "SECURITY-APPNAME": EBAY_APP_ID, "RESPONSE-DATA-FORMAT": "XML",
        "keywords": keyword, "itemFilter(0).name": "SoldItemsOnly",
        "itemFilter(0).value": "true",
        "paginationInput.entriesPerPage": "3",
        "sortOrder": "EndTimeSoonest"
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        if "errorMessage" in resp.text:
            return None
        root = ET.fromstring(resp.text)
        ns = {'ns': 'http://www.ebay.com/marketplace/search/v1/services'}
        price_nodes = root.findall(".//ns:currentPrice", ns)
        prices = []
        for p in price_nodes:
            if p.text:
                prices.append(float(p.text))
        if not prices: return None
        return sum(prices) / len(prices)
    except Exception as e:
        logger.warning(f"get_market_price Finding API failed (keyword={keyword!r}): {e}")
        return None

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Winning Titles Test:", get_winning_titles("Pokemon PSA10 Pikachu"))
    print("Sold Velocity (7d):", get_sold_velocity("Pokemon PSA10 Pikachu"))
    print("Market Price:", get_market_price("Pokemon PSA10 Pikachu"))
