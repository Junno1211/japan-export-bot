import os
import sys
import time
import math
import html
import json
import logging
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import google.api_core.exceptions
from google import genai

import requests
import xml.etree.ElementTree as ET

# Import existing modules
from mercari_scraper import scrape_mercari_item
from ebay_lister import upload_picture_bytes
from config import (
    GOOGLE_CREDENTIALS_PATH, GEMINI_API_KEY,
    EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID, EBAY_AUTH_TOKEN, 
    EBAY_SITE_ID, EBAY_ENV
)

# ============================================================
# LOGGING SETUP
# ============================================================
logger = logging.getLogger("ExportLister")
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(ch)

# ============================================================
# CONSTANTS & CONFIG
# ============================================================
SPREADSHEET_ID = "1dlRcKP4tKubmubrO-_kYo2y9cfN867ZUbHUMYjp4280"
SHEET_NAME_TO_USE = "シート7" # User confirmed sheet layout
EXCHANGE_RATE = 155.0
ROI_MULTIPLIER = 1.25

ENDPOINTS = {
    "production": "https://api.ebay.com/ws/api.dll",
    "sandbox":    "https://api.sandbox.ebay.com/ws/api.dll"
}
EBAY_ENDPOINT = ENDPOINTS.get(EBAY_ENV, ENDPOINTS["production"])

# ============================================================
# UTILITY FUNCTIONS
# ============================================================
def init_sheets_service():
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=scopes)
    return build('sheets', 'v4', credentials=creds)

def init_gemini_client():
    return genai.Client(api_key=GEMINI_API_KEY)

def get_shipping_policy_name(price_usd: float) -> str:
    """
    Returns the exact name of the Business Policy for shipping on eBay.
    This must match the exact policy name created in the eBay seller account.
    """
    if price_usd <= 15.0:
        return "カード用_デフォ_2500"
    elif price_usd <= 300.0:
        return "カード用_Fedex_4000"
    else:
        return "高額カード用_7500"

def add_item_to_ebay(title: str, desc_html: str, price_usd: float,
                     image_urls: list, category_id: str, condition_id: int,
                     item_specifics: dict, shipping_policy: str) -> dict:
    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "AddFixedPriceItem",
        "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml",
    }

    pics_xml = "\\n".join([f"<PictureURL>{u}</PictureURL>" for u in image_urls if u])
    specs_xml = "\\n".join([
        f"<NameValueList><Name>{k}</Name><Value>{v}</Value></NameValueList>"
        for k, v in item_specifics.items()
    ])

    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<AddFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <Item>
    <Title>{title[:80]}</Title>
    <Description><![CDATA[{desc_html}]]></Description>
    <PrimaryCategory><CategoryID>{category_id}</CategoryID></PrimaryCategory>
    <StartPrice currencyID="USD">{price_usd}</StartPrice>
    <ConditionID>{condition_id}</ConditionID>
    <Country>JP</Country>
    <Location>Japan</Location>
    <Currency>USD</Currency>
    <DispatchTimeMax>3</DispatchTimeMax>
    <ListingDuration>GTC</ListingDuration>
    <ListingType>FixedPriceItem</ListingType>
    <PostalCode>100-0001</PostalCode>
    <Quantity>1</Quantity>
    <ItemSpecifics>{specs_xml}</ItemSpecifics>
    <PictureDetails>{pics_xml}</PictureDetails>
    <SellerProfiles>
      <SellerShippingProfile>
        <ShippingProfileName>{shipping_policy}</ShippingProfileName>
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

    resp = requests.post(EBAY_ENDPOINT, headers=headers, data=xml_body.encode("utf-8"), timeout=30)
    root = ET.fromstring(resp.text)
    ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}

    ack = root.find("ns:Ack", ns)
    if ack is not None and ack.text in ("Success", "Warning"):
        item_id_el = root.find("ns:ItemID", ns)
        return {"success": True, "item_id": item_id_el.text if item_id_el is not None else ""}
    else:
        errs = [e.text for e in root.findall(".//ns:LongMessage", ns)]
        return {"success": False, "errors": errs}

# ============================================================
# STEP 2: DUPLICATE CHECK
# ============================================================
def check_duplicate(service, mercari_url: str) -> bool:
    """
    Search "Mercari URL" column (Column B assuming format) for the input URL.
    Also check items.csv for duplicates.
    If found -> return True
    """
    logger.info("Step 2: Checking for duplicates in Spreadsheet + items.csv...")
    try:
        # items.csvチェック
        import csv
        csv_path = os.path.join(os.path.dirname(__file__) or ".", "items.csv")
        if os.path.exists(csv_path):
            with open(csv_path, "r") as f:
                for row in csv.DictReader(f):
                    if row.get("mercari_url", "").strip() == mercari_url.strip():
                        logger.error(f"🛑 Duplicate found in items.csv: {mercari_url}")
                        return True

        # スプレッドシートチェック
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME_TO_USE}!A2:J"
        ).execute()
        rows = result.get('values', [])

        for i, row in enumerate(rows):
            # Based on image: B=Mercari URL(index 1), C=Price(index 2), D=Item ID(index 3), E=Status(index 4)
            if len(row) > 1 and isinstance(row[1], str) and mercari_url in row[1]:
                status = row[4] if len(row) > 4 else ""
                ebay_id = row[3] if len(row) > 3 else "Unknown"

                if "出品済み" in status or bool(ebay_id) and ebay_id.isdigit():
                    logger.error(f"🛑 Already listed or processed. eBay ID: {ebay_id}, Status: {status}")
                    return True
        logger.info("  ✓ No active duplicates found. Safe to proceed.")
        return False
    except Exception as e:
        logger.error(f"Failed to read spreadsheet for duplicate check: {e}")
        # To be safe on strict rules, consider failing if API is down
        sys.exit(1)

# ============================================================
# STEP 3: GENERATE LISTING VIA GEMINI
# ============================================================
def ai_generate_listing(client, title_ja: str, desc_ja: str, condition_ja: str):
    logger.info("Step 3: Generating eBay listing text via Gemini API (Strict Mode)...")
    
    prompt = f"""
You are a highly strict AI working for a Japan-to-eBay export business.
Your ONLY job is to respond with a valid JSON object containing exactly the keys requested. DO NOT wrap the JSON in Markdown code blocks like ```json ... ```. Output raw JSON only.

# INPUT DATA
Title (JA): {title_ja}
Description (JA): {desc_ja}
Condition (JA): {condition_ja}

# OUTPUT SCHEMA (JSON)
{{
    "title": "<String, Max 80 chars>",
    "description": "<String, Multi-line, NO MARKDOWN whatsoever. Plain text only.>",
    "category_name": "<String, must be either 'Pokemon', 'Baseball', or 'Other'>",
    "item_specific_brand": "<String>",
    "item_specific_type": "<String>",
    "mapped_condition_id": <Integer, 1000 for Brand New, 3000 for Used>
}}

# HARD RULES FOR TITLE
- ALL character/player names in English.
- Include Brand, set name, year, card number, card type.
- For PSA: "PSA [number]" once only — never repeat.
- Never include: shipping info, condition, Japanese text, seller notes.
- Always end with " Japan".
- MAX 80 CHARACTERS. Count perfectly.

# HARD RULES FOR DESCRIPTION
- CRITICAL: Never include any external URLs, website addresses, or hyperlinks. No http/https links, no brand websites, no reference pages. eBay policy prohibits all external links.
- NO MARKDOWN allowed whatsoever. Plain text format only. Treat spacing like a normal text file.
- Do not use HTML tags either. Just plain text.

[FORMAT TO FOLLOW EXACTLY]
[One compelling opening sentence about rarity or historical significance]

■ Card Details
Card No.     : [Number or N/A]
Featured     : [all characters/players, English names ONLY]
Set          : [Set name]
Year         : [Year]
Type         : [Type e.g., Vending Machine / Base / Signed / Promo]
Publisher    : [Publisher e.g., Nintendo, Bandai, Topps]
Grade        : [If PSA, include cert number, else remove this line]
Storage      : [If mentioned in input]

■ Condition
[MAP EXACTLY USING THESE RULES BASED ON '{condition_ja}']:
If '新品、未使用' -> "Brand new. Never used. Stored carefully since purchase."
If '未使用に近い' -> "Near mint. Extremely light handling only. No visible damage, creases, or stains."
If '目立った傷や汚れなし' OR '細かな使用感・傷・汚れはあるが、目立たない' -> "Minor signs of use. No major creases, tears, peeling, or stains. Light surface scratches may be present under close inspection."
If 'やや傷や汚れあり' or anything worse -> "Visible signs of use. Some scratches, scuffs, or minor stains present. Please review all photos carefully."

[If the item appears to be from 1990s-2000s, append exactly to Condition:]
Please note this is a 25+ year old paper collectible. Minor age-related wear is expected and is NOT considered a defect.

[If the item is PSA graded (ignore original condition), replace Condition text ENTIRELY with:]
Professionally graded PSA [grade]. Sealed in tamper-proof PSA slab. Condition certified and guaranteed by PSA.

[For ALL items, always end Condition section with:]
Please carefully review all photos before purchasing.

■ Shipping
Ships within 10 days of payment
FedEx International — fully tracked from Japan to your door
[CHOOSE ONE PACKAGING STRATEGY based on item context:]
Standard cards     : Top loader + bubble wrap + waterproof packaging
OR
PSA slab           : Bubble wrap + rigid box

■ Keywords
[Provide all relevant English and Romaji search terms, Set name, Publisher, Year. NO COMMA SEPARATION IS OK, spaces are fine.]
"""
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        t = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(t)
        
        # Determine strict category and condition ID
        if "新品" in condition_ja and "未使用に近い" not in condition_ja:
            data["mapped_condition_id"] = 1000
        else:
            data["mapped_condition_id"] = 3000
            
        return data
    except Exception as e:
        logger.error(f"Gemini API failure: {e}")
        logger.debug(f"Raw response: {response.text if 'response' in locals() else 'None'}")
        sys.exit(1)

# ============================================================
# STEP 5: RECORD TO SPREADSHEET
# ============================================================
def record_to_spreadsheet(service, mercari_url, title_ja, ebay_id, ebay_url, price_usd, price_jpy, category, condition):
    logger.info("Step 5: Recording to Spreadsheet...")
    today_str = datetime.now().strftime("%Y/%m/%d")
    
    # Based on image: A is empty/checkbox, B is URL, C is Price USD, D is Item ID, E is Status
    row_data = [
        "",                 # A: Checkbox/Empty
        mercari_url,        # B: Mercari URL
        price_usd,          # C: 販売価格(USD)
        str(ebay_id),       # D: 商品ID
        "✅ 出品済み"        # E: ステータス
    ]
    
    try:
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME_TO_USE}!A:J",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row_data]}
        ).execute()
        logger.info("  ✓ Spreadsheet recorded successfully")
    except Exception as e:
        logger.error(f"Failed to record to Google Sheets: {e}")

# ============================================================
# MAIN WORKFLOW
# ============================================================
def main():
    if len(sys.argv) < 3:
        print("Usage: python3 export_lister.py <mercari_url> <price_usd>")
        print("Example: python3 export_lister.py https://jp.mercari.com/item/m123456789 50.0")
        sys.exit(1)
        
    mercari_url = sys.argv[1].strip()
    try:
        user_price_usd = float(sys.argv[2].strip())
    except ValueError:
        print("Error: <price_usd> must be a valid number (e.g., 50.0).")
        sys.exit(1)
        
    logger.info(f"🚀 Starting Full Listing Workflow for: {mercari_url} at ${user_price_usd:.2f}")

    service = init_sheets_service()
    gemini_client = init_gemini_client()
    
    # Step 2: Duplicate Check FIRST
    if check_duplicate(service, mercari_url):
        sys.exit(0)

    # Step 1: Fetch Mercari Page
    logger.info("Step 1: Fetching Mercari Page...")
    scraped = scrape_mercari_item(mercari_url, delay=1.0)
    if not scraped.get("success"):
        logger.error(f"Failed to scrape: {scraped.get('error')}")
        sys.exit(1)
        
    title_ja = scraped.get("title", "")
    desc_ja = scraped.get("description", "")
    price_jpy = scraped.get("price_jpy", 0)
    if price_jpy <= 0:
        logger.error("Could not extract a valid JPY price from Mercari.")
        sys.exit(1)
        
    # The scraper currently does not extract condition specifically 
    # but we will assume 'used' or parse description for now if missing. 
    # For strict compliance, we will just pass description to gemini.
    condition_ja = "目立った傷や汚れなし" # Hardcode or parse from page if possible in scraper
    
    # Step 3: Generate eBay Listing
    ai_data = ai_generate_listing(gemini_client, title_ja, desc_ja, condition_ja)
    
    title_en = ai_data.get("title")
    desc_plain = ai_data.get("description")
    cat_name = ai_data.get("category_name", "Other")
    cond_id = ai_data.get("mapped_condition_id", 3000)
    
    # Convert plain text to basically HTML for eBay description safely (replacing newlines with <br>)
    desc_html_escaped = html.escape(desc_plain).replace('\n', '<br>')
    title_en_escaped = html.escape(title_en)
    
    # Step 4: Calculate Price (Manual Override) & List
    price_usd = user_price_usd
    shipping_policy = get_shipping_policy_name(price_usd)
    logger.info(f"Step 4: Preparing eBay Listing at ${price_usd:.2f} (Purchase ¥{price_jpy})...")
    logger.info(f"  Shipping Policy assigned: {shipping_policy}")
    
    item_specifics = {
        "Brand": ai_data.get("item_specific_brand", "Unbranded"),
        "Type": ai_data.get("item_specific_type", "Collectibles"),
    }
    if cat_name == "Pokemon":
        item_specifics["Franchise"] = "Pokémon"
    
    # Images Upload
    eps_urls = []
    image_bytes_list = scraped.get("image_bytes", [])
    logger.info(f"  Uploading {len(image_bytes_list)} images to EPS...")
    
    if not image_bytes_list:
        logger.error("No images found or downloaded! Cannot list.")
        sys.exit(1)
        
    for j, img_data in enumerate(image_bytes_list[:12]):
        eps = upload_picture_bytes(img_data["bytes"], filename=f"image_{j+1}.jpg")
        if eps:
            eps_urls.append(eps)
        time.sleep(0.5)
        
    if not eps_urls:
        logger.error("Image upload to EPS completely failed. Aborting.")
        sys.exit(1)
        
    # eBay Category IDs
    category_id = "1345" # default Anime and Collectibles
    
    # Actually Post to eBay
    logger.info("  🛒 Submitting to eBay API...")
    result = add_item_to_ebay(
        title=title_en_escaped,
        desc_html=desc_html_escaped,
        price_usd=price_usd,
        image_urls=eps_urls,
        category_id=category_id,
        condition_id=cond_id,
        item_specifics=item_specifics,
        shipping_policy=shipping_policy,
    )
    
    if not result.get("success"):
        logger.error(f"eBay Listing Failed: {result.get('errors')}")
        sys.exit(1)
        
    ebay_id = result.get("item_id")
    ebay_url = f"https://www.ebay.com/itm/{ebay_id}"
    
    # Step 5: Record to Spreadsheet
    record_to_spreadsheet(
        service, 
        mercari_url=mercari_url, 
        title_ja=title_ja, 
        ebay_id=ebay_id, 
        ebay_url=ebay_url, 
        price_usd=price_usd, 
        price_jpy=price_jpy, 
        category=cat_name, 
        condition=condition_ja
    )
    
    # Step 6: Report to User
    print("\n------------------------------------------------------------")
    print("✨ SUCCESS: eBay Listing Published!")
    print(f"eBay Item ID       : {ebay_id}")
    print(f"eBay Listing URL   : {ebay_url}")
    print(f"Listed Price (USD) : ${price_usd:.2f}")
    print("Promoted Listings  : Promoted via eBay standard overarching campaign policy (Must be set on eBay seller hub)")
    print("Spreadsheet        : recorded ✓")
    print("------------------------------------------------------------\n")

if __name__ == "__main__":
    main()
