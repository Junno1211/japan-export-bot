import requests
from config import EBAY_APP_ID, EBAY_DEV_ID, EBAY_CERT_ID, EBAY_AUTH_TOKEN, EBAY_SITE_ID, EBAY_ENV, SPREADSHEET_ID, SHEET_NAME
from sheets_manager import _get_service, delete_rows, get_sheet_id_by_name

endpoint = "https://api.ebay.com/ws/api.dll" if EBAY_ENV == "production" else "https://api.sandbox.ebay.com/ws/api.dll"

def end_item(item_id):
    if not item_id or len(str(item_id)) < 5: return
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
    print(f"Ended on eBay {item_id}: {resp.status_code}")

service = _get_service()

# 1. READ MASTER SHEET TO END ITEMS
res = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:F500").execute()
rows = res.get("values", [])
rows_to_delete = []
for i, row in enumerate(rows):
    if len(row) > 0 and row[0].strip():
        end_item(row[0].strip())
        rows_to_delete.append(i+2)

# 2. DELETE ALL FROM MASTER SHEET
if rows_to_delete:
    delete_rows(SHEET_NAME, rows_to_delete)
    print(f"Deleted {len(rows_to_delete)} rows from Master Sheet.")

# 3. CLEAR SHEET 7 STATUS
res = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range="シート7!A2:E200").execute()
rows = res.get("values", [])
updates = []
for i, row in enumerate(rows):
    if len(row) > 0 and row[0].strip():
        # Clear Item ID (Col C) and Status (Col D)
        updates.append({
            "range": f"シート7!C{i+2}:E{i+2}",
            "values": [["", "", ""]]
        })

if updates:
    body = {"valueInputOption": "USER_ENTERED", "data": updates}
    service.spreadsheets().values().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=body).execute()
    print(f"Cleared status for {len(updates)} rows in Sheet 7.")

print("Wipe complete!")
