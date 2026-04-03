import os
import sys
import argparse
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SPREADSHEET_ID = "1dlRcKP4tKubmubrO-_kYo2y9cfN867ZUbHUMYjp4280"
SHEET_NAME = "シート7"

def get_sheets_service():
    CREDENTIALS_FILE = 'google_credentials.json'
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"Error: {CREDENTIALS_FILE} not found.")
        sys.exit(1)
        
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    return build('sheets', 'v4', credentials=creds)

def main():
    print(f"Starting Batch Export Lister for Master Sheet: {SHEET_NAME}")
    service = get_sheets_service()
    sheet = service.spreadsheets()
    
    # Range is dynamically determined, assume columns A to E
    range_name = f"{SHEET_NAME}!A:E"
    
    try:
        result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=range_name).execute()
        values = result.get('values', [])
    except Exception as e:
        print(f"Failed to fetch spreadsheet: {e}")
        return

    if not values:
        print("No data found in spreadsheet.")
        return

    headers = values[0]
    print(f"Headers found: {headers}")
    
    # Process each row
    for index, row in enumerate(values[1:], start=2): # +1 for 0-index, +1 for header
        # Pad row to match 5 columns if necessary (A, B, C, D, E)
        while len(row) < 5:
            row.append("")
            
        mercari_url = row[1].strip()
        price_usd_str = row[2].strip()
        item_id = row[3].strip()
        status = row[4].strip()
        
        # Skip if no URL or no Price set
        if not mercari_url or not price_usd_str:
            continue
            
        # Skip if already listed or has a status
        if status or item_id:
            continue
            
        print(f"\n[{index}] Processing pending item: {mercari_url} at target price ${price_usd_str}")
        
        try:
            target_price = float(price_usd_str)
        except ValueError:
            print(f"  ❌ Invalid price format: {price_usd_str}. Marking as error.")
            update_status(service, index, "Error: Invalid Price")
            continue
            
        # Use this URL for testing
        print(f"  [FOUND TEST TARGET]: {mercari_url}")
        
        # We just want 3 targets to test
        if index > 4:
             return
        
        # Update sheet with success
        # update_row(service, index, simulated_ebay_id, "✅ 出品済み")

def update_status(service, row_number, status_msg):
    # Just update column E (Status)
    range_name = f"{SHEET_NAME}!E{row_number}"
    body = {'values': [[status_msg]]}
    try:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID, range=range_name,
            valueInputOption="RAW", body=body).execute()
    except Exception as e:
        print(f"Failed to update status on row {row_number}: {e}")

if __name__ == "__main__":
    main()
