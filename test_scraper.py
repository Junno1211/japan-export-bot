from curl_cffi import requests
from bs4 import BeautifulSoup
import json

url = "https://jp.mercari.com/item/m19246016666"
print(f"Scraping {url} using requests...")

headers = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache"
}

try:
    response = requests.get(url, headers=headers, impersonate="chrome", timeout=15)
    print("Status Code:", response.status_code)
    
    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.string if soup.title else "No Title"
    
    # Try finding __NEXT_DATA__ which contains all item details
    next_data_script = soup.find("script", id="__NEXT_DATA__")
    if next_data_script:
        data = json.loads(next_data_script.string)
        # Parse logic would go here, for now just confirm we have it
        print("✅ Found __NEXT_DATA__")
        # Let's try to find title or price deeply in JSON if possible, but just checking if it exists is a huge win.
    else:
        print("❌ __NEXT_DATA__ not found. Showing body snippet:")
        print(soup.body.text[:500] if soup.body else "No body")
        
    print("Page Title:", title)
except Exception as e:
    print(f"Error: {e}")
