from scrapingbee import ScrapingBeeClient
import json

API_KEY = "9ZYQ36X44UB75LGAAII9S5FGUB8ORXDF3WQB1665T20JYFJE5FTHCDJRY5F1ZT1FULF9SRJOCIQXOOLM"
client = ScrapingBeeClient(api_key=API_KEY)

url = "https://jp.mercari.com/item/m81699855325"
print(f"Testing ScrapingBee direct fetch for {url}...")

# Use premium proxy specifically for Japan and enable JS rendering for React/Next.js
response = client.get(
    url,
    params={
        "render_js": "true",
        "premium_proxy": "true",
        "stealth_proxy": "true",
        "country_code": "jp",
        "device": "mobile",
        "wait": "3000"
    }
)

if response.ok:
    print(f"✅ Success! Status Code: {response.status_code}")
    print("Saving response to debug_scrapingbee.html...")
    with open("debug_scrapingbee.html", "w", encoding="utf-8") as f:
        f.write(response.text)
        
    print(f"HTML Length: {len(response.text)} bytes")
else:
    print(f"❌ Failed! Status Code: {response.status_code}")
    print(f"Response snippet: {response.text[:500]}")
