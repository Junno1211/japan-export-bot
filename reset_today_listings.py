import os, sys, requests, xml.etree.ElementTree as ET
from config import EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID, EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV, SPREADSHEET_ID, SHEET_NAME
from sheets_manager import _get_service, delete_rows, get_sheet_id_by_name

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
res = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range="シート7!A2:E50").execute()
rows = res.get("values", [])

reset_count = 0
for i, row in enumerate(rows):
    if len(row) > 3 and "出品済み" in row[3]:
        item_id = row[2]
        print(f"Found listed item on Row {i+2}: {item_id}")
        end_item(item_id)
        # Clear status on Sheet 7
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"シート7!C{i+2}:D{i+2}",
            valueInputOption="USER_ENTERED",
            body={"values": [["", ""]]}
        ).execute()
        reset_count += 1

# Now remove from Master Sheet
res2 = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A1:F500").execute()
master_rows = res2.get("values", [])
rows_to_delete = []
for i, row in enumerate(master_rows):
    if len(row) > 0 and len(row[0]) > 8: # If row[0] is an eBay ID
        # Check if it was listed today by just assuming the bottom-most / top-most recent are today.
        # Actually I can just delete ALL items in Master Sheet because today was the first day!
        # Let's just delete rows where Status == "Active" and it's near the top. 
        # Wait, the user has been listing items manually before our script?
        pass

print(f"Reset {reset_count} items from Sheet 7.")
