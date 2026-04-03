import requests, os, sys, json
from config import EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID, EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV, SPREADSHEET_ID, SHEET_NAME
from sheets_manager import _get_service, delete_rows

endpoint = "https://api.ebay.com/ws/api.dll" if EBAY_ENV == "production" else "https://api.sandbox.ebay.com/ws/api.dll"

def end_item(item_id):
    if not item_id or len(str(item_id)) < 5: return False
    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME": "EndFixedPriceItem",
        "X-EBAY-API-SITEID": str(EBAY_SITE_ID),
        "X-EBAY-API-APP-NAME": EBAY_APP_ID,
        "X-EBAY-API-DEV-NAME": EBAY_DEV_ID,
        "X-EBAY-API-CERT-NAME": EBAY_CERT_ID,
        "Content-Type": "text/xml"
    }
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<EndFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{EBAY_AUTH_TOKEN}</eBayAuthToken></RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <EndingReason>NotAvailable</EndingReason>
</EndFixedPriceItemRequest>"""
    try:
        resp = requests.post(endpoint, headers=headers, data=xml_body.encode("utf-8"))
        if "Success" in resp.text or "Warning" in resp.text:
            print(f"Ended {item_id} successfully.")
            return True
        else:
            print(f"Failed to end {item_id}: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"Exception ending {item_id}: {e}")
        return False

service = _get_service()

# 1. Read Sheet 7 to find all mercari URLs that were listed
res = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range="シート7!A2:E200").execute()
sheet7_rows = res.get("values", [])

urls_in_sheet7 = set()
for row in sheet7_rows:
    if len(row) > 0 and row[0].strip().startswith("http"):
        urls_in_sheet7.add(row[0].strip())

print(f"Found {len(urls_in_sheet7)} URLs in Sheet 7.")

# 2. Match URLs against Master Sheet (在庫管理表) to find eBay IDs
res_master = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:F5000").execute()
master_rows = res_master.get("values", [])

rows_to_delete_from_master = []
items_ended = 0

for i, row in enumerate(master_rows):
    if len(row) > 1:
        ebay_id = row[0].strip()
        mercari_url = row[1].strip()
        
        # If the item in master sheet is also in Sheet 7, it means it was auto-listed from Sheet 7
        if mercari_url in urls_in_sheet7:
            if end_item(ebay_id):
                items_ended += 1
            rows_to_delete_from_master.append(i + 2)  # +2 because A2 is index 0

# Delete them from master sheet
if rows_to_delete_from_master:
    delete_rows(SHEET_NAME, rows_to_delete_from_master)
    print(f"Deleted {len(rows_to_delete_from_master)} corresponding rows from Master Sheet.")

# 3. Clear the status columns (C, D) in Sheet 7 so they can be re-listed
updates = []
for i, row in enumerate(sheet7_rows):
    if len(row) > 0 and row[0].strip().startswith("http"):
        updates.append({
            "range": f"シート7!C{i+2}:E{i+2}",
            "values": [["", "", ""]]
        })

if updates:
    body = {"valueInputOption": "USER_ENTERED", "data": updates}
    service.spreadsheets().values().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=body).execute()
    print(f"Cleared status for {len(updates)} rows in Sheet 7.")

print(f"Totally ended {items_ended} active listings on eBay.")
