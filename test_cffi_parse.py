import re
import json

def extract():
    with open("debug_cffi.html", "r", encoding="utf-8") as f:
        html = f.read()

    print(f"File size: {len(html)}")

    # Try to find the JSON bundle embedded in the SSR Next.js output
    # Usually name:"Product Name", price:1000
    
    # 1. Look for name
    # The JSON structure in the Next_f chunks looks like "name":"ポケモンカード","price":3000
    names = re.findall(r'"name":"([^"]+)"', html)
    name = next((n for n in set(names) if "メルカリ" not in n and len(n) > 2), "Unknown Name")
    print(f"Title: {name}")

    # 2. Look for price
    # Need to be careful. The price might be "price":3000
    # There are many prices (recommendations), but usually the primary item is first or has specific structure
    prices = re.findall(r'"price":(\d+)', html)
    if prices:
        # We assume the first or most common non-zero price could be it, 
        # but let's just print them to see
        print(f"Found {len(prices)} prices. Top 3: {prices[:3]}")
    
    # 3. Look for images
    images = re.findall(r'(https://static\.mercdn\.net/item/detail/orig/photos/m\d+_\d+\.jpg)', html)
    unique_images = []
    for img in images:
        if img not in unique_images:
            unique_images.append(img)
            
    print(f"Found {len(unique_images)} images:")
    for img in unique_images[:5]:
        print(f"  {img}")
        
    # 4. Description
    descs = re.findall(r'"description":"([^"]+)"', html)
    print(f"Found {len(descs)} descriptions.")
    if descs:
        print(f"Sample: {descs[0][:100]}...")

extract()
