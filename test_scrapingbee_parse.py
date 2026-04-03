from bs4 import BeautifulSoup
import json
import re

print("Parsing debug_scrapingbee.html...")

with open("debug_scrapingbee.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

# 1. Title
title = soup.title.string if soup.title else ""
# Real item title is typically in an h1:
h1 = soup.find("h1")
item_name = h1.text.strip() if h1 else title

# 2. Price
price_el = soup.find(attrs={"data-testid": "price"})
price = 0
if price_el:
    # Remove non-digits
    price_str = re.sub(r'[^0-9]', '', price_el.text)
    price = int(price_str) if price_str else 0

# 3. Description
desc_el = soup.find("pre", attrs={"data-testid": "description"})
description = desc_el.text.strip() if desc_el else ""

# 4. Images
image_urls = []
# Mercari recently uses <mer-item-thumbnail> or slides
# Let's just find all high-res image URLs in the document that look like mercdn.net
# The best way is to find <img src="..."> matching "https://static.mercdn.net/item/detail/orig/"
imgs = soup.find_all("img")
for img in imgs:
    src = img.get("src") or ""
    if "static.mercdn.net/item/detail/orig/photos/" in src:
        if src not in image_urls:
            image_urls.append(src)

# If orig not found, look for whatever photos
if not image_urls:
    for img in imgs:
        src = img.get("src") or ""
        if "static.mercdn.net" in src and "photos" in src:
            # Try to convert to orig high res
            # e.g. https://static.mercdn.net/c!/w=240/thumb/photos/m19246016666_1.jpg?1700445550
            # to https://static.mercdn.net/item/detail/orig/photos/m19246016666_1.jpg
            match = re.search(r'(m\d+_\d+\.jpg)', src)
            if match:
                orig_url = f"https://static.mercdn.net/item/detail/orig/photos/{match.group(1)}"
                if orig_url not in image_urls:
                    image_urls.append(orig_url)

# 5. Condition
# In mercari, the condition is usually in a table cell next to a header "商品の状態"
condition = "目立った傷や汚れなし" # fallback
th = soup.find("th", string="商品の状態")
if th:
    td = th.find_next_sibling("td")
    if td:
        condition = td.text.strip()
# Let's try more robust if simple 'th' check fails:
if not th:
    for span in soup.find_all("span"):
        if span.text == "商品の状態":
            val_el = span.find_next()
            if val_el:
                condition = val_el.text.strip()

data = {
    "title": item_name,
    "price": price,
    "description": description,
    "images": image_urls,
    "condition": condition
}

print(json.dumps(data, indent=2, ensure_ascii=False))
