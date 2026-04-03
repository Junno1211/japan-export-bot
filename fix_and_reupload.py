import requests, os, sys
from config import EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID, EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV, SPREADSHEET_ID, SHEET_NAME
from sheets_manager import _get_service, delete_rows

endpoint = "https://api.ebay.com/ws/api.dll" if EBAY_ENV == "production" else "https://api.sandbox.ebay.com/ws/api.dll"

def end_item(item_id):
    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "EndFixedPriceItem",
        "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml"
    }
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<EndFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <EndingReason>NotAvailable</EndingReason>
</EndFixedPriceItemRequest>"""
    resp = requests.post(endpoint, headers=headers, data=xml.encode("utf-8"))
    print(f"Ended {item_id}: {resp.status_code}")

service = _get_service()

# Clear the specific item from Sheet 7
mercari_url = "https://jp.mercari.com/item/m81699855131"
res = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range="シート7!A2:E20").execute()
rows = res.get("values", [])
for i, row in enumerate(rows):
    if len(row) > 0 and mercari_url in row[0]:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"シート7!C{i+2}:E{i+2}",
            valueInputOption="USER_ENTERED",
            body={"values": [["", "", ""]]}
        ).execute()
        print(f"Cleared status on row {i+2}")

# Delete from Master Sheet
res2 = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:B500").execute()
master_rows = res2.get("values", [])
rows_to_delete = []
for i, row in enumerate(master_rows):
    if len(row) > 1 and mercari_url in row[1]:
        end_item(row[0].strip())
        rows_to_delete.append(i+2)

if rows_to_delete:
    delete_rows(SHEET_NAME, rows_to_delete)
    print("Cleaned up Master Sheet.")
