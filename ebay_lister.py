import requests
import xml.etree.ElementTree as ET
import logging
import sys
from common_rules import TITLE_MAX_LENGTH
from config import EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID, EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

ENDPOINTS = {
    "production": "https://api.ebay.com/ws/api.dll",
    "sandbox":    "https://api.sandbox.ebay.com/ws/api.dll"
}

def _make_headers(call_name: str) -> dict:
    return {
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": call_name,
        "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml",
    }

def upload_picture(external_url: str) -> str:
    """メルカリの画像URLをeBayに渡し、eBay専用の画像URL(EPS URL)に変換する"""
    endpoint = ENDPOINTS.get(EBAY_ENV, ENDPOINTS["production"])
    
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<UploadSiteHostedPicturesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <ExternalPictureURL>{external_url}</ExternalPictureURL>
</UploadSiteHostedPicturesRequest>"""

    logging.info(f"Uploading image to eBay EPS: {external_url}")
    resp = requests.post(endpoint, headers=_make_headers("UploadSiteHostedPictures"), data=xml_body.encode("utf-8"), timeout=30)
    root = ET.fromstring(resp.text)
    ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
    
    ack = root.find("ns:Ack", ns)
    if ack is not None and ack.text in ("Success", "Warning"):
        site_url = root.find("ns:SiteHostedPictureDetails/ns:FullURL", ns)
        if site_url is not None:
            return site_url.text
    else:
        err = root.find(".//ns:LongMessage", ns)
        logging.error(f"Image upload failed: {err.text if err is not None else resp.text}")
    return ""


def _ensure_min_resolution(image_bytes: bytes, min_size: int = 500) -> bytes:
    """eBay EPSの最低解像度(500x500)を満たすようリサイズ"""
    try:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(image_bytes))
        w, h = img.size
        if w >= min_size and h >= min_size:
            return image_bytes
        scale = max(min_size / w, min_size / h)
        new_w, new_h = int(w * scale) + 1, int(h * scale) + 1
        img = img.resize((new_w, new_h), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90)
        logging.info(f"Image resized: {w}x{h} → {new_w}x{new_h}")
        return buf.getvalue()
    except Exception:
        return image_bytes


def upload_picture_bytes(image_bytes: bytes, filename: str = "image.jpg") -> str:
    """
    画像バイナリをマルチパートでeBay EPSにアップロードしてURLを返す
    （メルカリのホットリンク保護を回避するための方式）
    """
    import base64
    image_bytes = _ensure_min_resolution(image_bytes)
    endpoint = ENDPOINTS.get(EBAY_ENV, ENDPOINTS["production"])
    
    # eBayはXMLにbase64で埋め込む形式もサポート
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<UploadSiteHostedPicturesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <PictureName>{filename}</PictureName>
</UploadSiteHostedPicturesRequest>"""

    # multipart/form-data として画像バイナリをそのまま送信
    boundary = "MIME_boundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="XML payload"\r\n'
        f"Content-Type: text/xml;charset=UTF-8\r\n\r\n"
        f"{xml_body}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode("utf-8") + image_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "UploadSiteHostedPictures",
        "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }

    logging.info(f"Uploading image bytes ({len(image_bytes)} bytes) to eBay EPS")
    resp = requests.post(endpoint, headers=headers, data=body, timeout=30)
    root = ET.fromstring(resp.text)
    ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
    
    ack = root.find("ns:Ack", ns)
    if ack is not None and ack.text in ("Success", "Warning"):
        site_url = root.find("ns:SiteHostedPictureDetails/ns:FullURL", ns)
        if site_url is not None:
            return site_url.text
    else:
        err = root.find(".//ns:LongMessage", ns)
        logging.error(f"Image bytes upload failed: {err.text if err is not None else resp.text[:200]}")
    return ""

def verify_add_item(title: str, desc_html: str, price_usd: float, image_urls: list, category_id: str = "261328", item_specifics: dict = None) -> dict:
    """実際には出品されないテスト(VerifyAddFixedPriceItem)を使ってAPIの全項目を検証する"""
    endpoint = ENDPOINTS.get(EBAY_ENV, ENDPOINTS["production"])
    
    picture_details_xml = "<PictureDetails>\n"
    for url in image_urls:
        picture_details_xml += f"  <PictureURL>{url}</PictureURL>\n"
    picture_details_xml += "</PictureDetails>"
    
    item_specifics_xml = ""
    if item_specifics:
        # eBayが拒否するキーを除外
        _blocked_keys = {"Condition", "condition", "ConditionID"}
        item_specifics = {k: v for k, v in item_specifics.items() if k not in _blocked_keys}

        # Year Manufactured: 4桁の西暦のみ許可、不正なら削除
        if "Year Manufactured" in item_specifics:
            ym = "".join(filter(str.isdigit, str(item_specifics["Year Manufactured"])))[:4]
            if len(ym) == 4 and 1900 <= int(ym) <= 2030:
                item_specifics["Year Manufactured"] = ym
            else:
                del item_specifics["Year Manufactured"]

        if category_id in ["261328", "183454"] and "Game" not in item_specifics:
            item_specifics["Game"] = "Pokémon TCG"

        item_specifics_xml = "<ItemSpecifics>\n"
        for k, v in item_specifics.items():
            if not v or not str(v).strip(): continue
            item_specifics_xml += f"  <NameValueList><Name><![CDATA[{k}]]></Name><Value><![CDATA[{v}]]></Value></NameValueList>\n"
        item_specifics_xml += "</ItemSpecifics>\n"

    # 動的配送ポリシーの取得 (価格帯別)
    shipping_profile = "$0~$100"
    if price_usd >= 100:
        # 100ドル刻みでポリシー名を推定 (ユーザーの既存パターンに合わせる)
        base = int(price_usd // 100) * 100
        shipping_profile = f"${base}~${base+99}"
        # 特殊な高額帯対応 (1700ドルなど)
        if 1700 <= price_usd < 1800:
            shipping_profile = "$1,700-$1,749"

def add_item(title: str, desc_html: str, price_usd: float, image_urls: list, category_id: str = "261328", item_specifics: dict = None, sku: str = "") -> dict:
    """本番出品を実施する (AddFixedPriceItem)。sku にメルカリURLを入れておくと在庫管理で追跡可能"""
    endpoint = ENDPOINTS.get(EBAY_ENV, ENDPOINTS["production"])
    
    picture_details_xml = "<PictureDetails>\n"
    for url in image_urls:
        picture_details_xml += f"  <PictureURL>{url}</PictureURL>\n"
    picture_details_xml += "</PictureDetails>"
    
    item_specifics_xml = ""
    if item_specifics:
        # eBayが拒否するキーを除外
        _blocked_keys = {"Condition", "condition", "ConditionID"}
        item_specifics = {k: v for k, v in item_specifics.items() if k not in _blocked_keys}

        # Year Manufactured: 4桁の西暦のみ許可、不正なら削除
        if "Year Manufactured" in item_specifics:
            ym = "".join(filter(str.isdigit, str(item_specifics["Year Manufactured"])))[:4]
            if len(ym) == 4 and 1900 <= int(ym) <= 2030:
                item_specifics["Year Manufactured"] = ym
            else:
                del item_specifics["Year Manufactured"]

        if category_id in ["261328", "183454"] and "Game" not in item_specifics:
            item_specifics["Game"] = "Pokémon TCG"

        item_specifics_xml = "<ItemSpecifics>\n"
        for k, v in item_specifics.items():
            if not v or not str(v).strip(): continue
            item_specifics_xml += f"  <NameValueList><Name><![CDATA[{k}]]></Name><Value><![CDATA[{v}]]></Value></NameValueList>\n"
        item_specifics_xml += "</ItemSpecifics>\n"

    # 配送ポリシー
    shipping_profile = "$0~$100"
    if price_usd >= 100:
        base = int(price_usd // 100) * 100
        shipping_profile = f"${base}~${base+99}"
        if 1700 <= price_usd < 1800:
            shipping_profile = "$1,700-$1,749"

    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<AddFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <Item>
    <Title><![CDATA[{title[:TITLE_MAX_LENGTH]}]]></Title>
    <Description><![CDATA[{desc_html}]]></Description>
    <PrimaryCategory>
      <CategoryID>{category_id}</CategoryID>
    </PrimaryCategory>
    <StartPrice currencyID="USD">{price_usd}</StartPrice>
    <ConditionID>3000</ConditionID>
    <Country>JP</Country>
    <Location>Japan</Location>
    <Currency>USD</Currency>
    <DispatchTimeMax>3</DispatchTimeMax>
    <ListingDuration>GTC</ListingDuration>
    <ListingType>FixedPriceItem</ListingType>
    <PostalCode>100-0001</PostalCode>
    <Quantity>1</Quantity>
    <OutOfStockControl>true</OutOfStockControl>
    {"<SKU><![CDATA[" + sku + "]]></SKU>" if sku else ""}
    {item_specifics_xml}
    {picture_details_xml}
    <SellerProfiles>
      <SellerShippingProfile>
        <ShippingProfileName>{shipping_profile}</ShippingProfileName>
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

    logging.info(f"Producing REAL Listing: {title}")
    resp = requests.post(endpoint, headers=_make_headers("AddFixedPriceItem"), data=xml_body.encode("utf-8"), timeout=30)
    root = ET.fromstring(resp.text)
    ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
    
    ack = root.find("ns:Ack", ns)
    if ack is not None and ack.text in ("Success", "Warning"):
        item_id = root.find("ns:ItemID", ns).text
        return {"success": True, "item_id": item_id}
    else:
        errs = [e.text for e in root.findall(".//ns:LongMessage", ns)]
        return {"success": False, "errors": errs}

if __name__ == "__main__":
    # Test logic
    pass
