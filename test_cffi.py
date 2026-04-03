from curl_cffi import requests

print("Testing direct curl_cffi fetch with chrome120 impersonation...")
url = "https://jp.mercari.com/item/m81699855325"

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
    print("Success 200!")
    print(r.text[:500])
    with open("debug_cffi.html", "w") as f:
        f.write(r.text)
    
    if "m81699855325" in r.text and "メルカリ" in r.text:
       print("✅ Found target item ID in the response HTML!")
    else:
       print("❌ Did not find target item ID. Probably blocked or redirected to homepage.")
else:
    print(f"Failed: {r.status_code}")
