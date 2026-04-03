from scrapingbee import ScrapingBeeClient
import json

API_KEY = "9ZYQ36X44UB75LGAAII9S5FGUB8ORXDF3WQB1665T20JYFJE5FTHCDJRY5F1ZT1FULF9SRJOCIQXOOLM"
client = ScrapingBeeClient(api_key=API_KEY)

item_id = "m81699855325"
api_url = f"https://api.mercari.jp/items/get?id={item_id}"
print(f"Testing ScrapingBee API direct fetch for {api_url}...")

# Directly hit the backend JSON API using residential Japanese IPs
response = client.get(
    api_url,
    params={
        "render_js": "false",
        "premium_proxy": "true",
        "stealth_proxy": "true",
        "country_code": "jp"
    },
    headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "X-Platform": "web",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://jp.mercari.com",
        "Referer": f"https://jp.mercari.com/item/{item_id}"
    }
)

if response.ok:
    print(f"✅ Success! Status Code: {response.status_code}")
    print(f"Response (first 1000 chars): {response.text[:1000]}")
    try:
        data = json.loads(response.text)
        if "data" in data:
            print(f"Found item name: {data.get('data', {}).get('name')}")
            print("Successfully extracted JSON from backend!")
    except json.JSONDecodeError:
        print("Not valid JSON!")
else:
    print(f"❌ Failed! Status Code: {response.status_code}")
    print(f"Response: {response.text[:1000]}")
