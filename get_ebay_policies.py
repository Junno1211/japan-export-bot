import os
import sys
import logging
import requests
import xml.etree.ElementTree as ET
from config import EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID, EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

ENDPOINTS = {
    "production": "https://api.ebay.com/ws/api.dll",
    "sandbox":    "https://api.sandbox.ebay.com/ws/api.dll"
}

def get_seller_profiles():
    endpoint = ENDPOINTS.get(EBAY_ENV, ENDPOINTS["production"])
    
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetSellerListRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <Pagination>
    <EntriesPerPage>1</EntriesPerPage>
    <PageNumber>1</PageNumber>
  </Pagination>
  <StartTimeFrom>2023-01-01T00:00:00.000Z</StartTimeFrom>
  <StartTimeTo>2024-01-01T00:00:00.000Z</StartTimeTo>
  <DetailLevel>ReturnAll</DetailLevel>
</GetSellerListRequest>"""
    
    # Actually GetSellerProfiles is not in Trading API, let's use GetMyeBaySelling or GetItem on one of their items to see the policies used.
    # We already have an item ID from their spreadsheet: 366244308142. Let's GetItem on it to see its SellerProfiles.
    pass

def get_item_profiles(item_id):
    endpoint = ENDPOINTS.get(EBAY_ENV, ENDPOINTS["production"])
    
    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "GetItem",
        "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml",
    }

    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken>
  </RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <DetailLevel>ReturnAll</DetailLevel>
</GetItemRequest>"""

    response = requests.post(endpoint, headers=headers, data=xml_body.encode("utf-8"))
    
    root = ET.fromstring(response.text)
    ns = {"ns": "urn:ebay:apis:eBLBaseComponents"}
    
    ack = root.find("ns:Ack", ns)
    if ack is not None and ack.text in ("Success", "Warning"):
        profiles = root.find(".//ns:SellerProfiles", ns)
        if profiles is not None:
            ship = profiles.find(".//ns:SellerShippingProfile/ns:ShippingProfileName", ns)
            ret = profiles.find(".//ns:SellerReturnProfile/ns:ReturnProfileName", ns)
            pay = profiles.find(".//ns:SellerPaymentProfile/ns:PaymentProfileName", ns)
            
            print(f"--- ポリシー情報 (Item: {item_id}) ---")
            print(f"Shipping: {ship.text if ship is not None else 'None'}")
            print(f"Return:   {ret.text if ret is not None else 'None'}")
            print(f"Payment:  {pay.text if pay is not None else 'None'}")
            
            # Let's also grab Category
            cat = root.find(".//ns:PrimaryCategory/ns:CategoryID", ns)
            cat_name = root.find(".//ns:PrimaryCategory/ns:CategoryName", ns)
            print(f"Category: {cat.text if cat is not None else 'None'} ({cat_name.text if cat_name is not None else ''})")
        else:
            print("SellerProfilesが見つかりません。")
            
        ship_details = root.find(".//ns:ShippingDetails", ns)
        if ship_details is not None:
            print("ShippingDetails が直接指定されています。")
    else:
        print("エラー:", response.text)

if __name__ == "__main__":
    get_item_profiles("366244308142")
    get_item_profiles("366126547071")
