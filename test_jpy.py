from mercari_scraper import scrape_mercari_item
import json

url = "https://jp.mercari.com/item/m76150259162"
res = scrape_mercari_item(url)
print(json.dumps({k: v for k, v in res.items() if k != "image_bytes"}, indent=2, ensure_ascii=False))
