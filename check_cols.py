from sheets_manager import _get_service
import sys

def main():
    service = _get_service()
    res = service.spreadsheets().values().get(
        spreadsheetId='1dlRcKP4tKubmubrO-_kYo2y9cfN867ZUbHUMYjp4280', 
        range='在庫管理表!A1:H5'
    ).execute()
    
    rows = res.get('values', [])
    for i, row in enumerate(rows):
        print(f"Row {i+1}: {row}")

if __name__ == '__main__':
    main()
