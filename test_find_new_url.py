from curl_cffi import requests
import re

print("Fetching Mercari search results to find a live URL...")
url = "https://jp.mercari.com/search?keyword=ポケモンカード"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": "\"Not_A Brand\";v=\"8\", \"Chromium\";v=\"120\", \"Google Chrome\";v=\"120\"",
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": "\"macOS\"",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}

r = requests.get(url, impersonate="chrome120", headers=headers)

if r.status_code == 200:
    # Find all item URLs
    items = re.findall(r'/item/(m\d+)', r.text)
    if items:
        unique_items = list(set(items))
        print(f"Found {len(unique_items)} live items. Top 3:")
        for item in unique_items[:3]:
            print(f"  https://jp.mercari.com/item/{item}")
    else:
        print("No items found. Blocked by Cloudflare?")
else:
    print(f"Failed: {r.status_code}")
