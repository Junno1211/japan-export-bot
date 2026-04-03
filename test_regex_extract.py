import re

def extract_raw_data():
    with open("debug_scrapingbee.html", "r", encoding="utf-8") as f:
        html = f.read()

    print(f"Total HTML length: {len(html)}")

    # Look for name indicator in the next.js chunks
    # Usually it looks like "name":"Pokemon Card..." or name:"Pokemon Card..."
    names = re.findall(r'"name":"([^"]+)"', html)
    print("Found 'name' definitions:")
    for i, n in enumerate(set(names)):
        if "メルカリ" not in n and len(n) > 5:
            print(f"  [{i}] {n}")

    # Look for price
    prices = re.findall(r'"price":(\d+)', html)
    print("\nFound 'price' definitions:")
    print(set(prices[:20])) # just print unique prices
    
    # Look for images starting with static.mercdn.net/item/detail/orig/photos
    # Or just m81699855325_X.jpg
    images = re.findall(r'(https://static\.mercdn\.net/item/detail/orig/photos/m\d+_\d+\.jpg)', html)
    # Also look for base photo URLs without https protocol
    images2 = re.findall(r'static\.mercdn\.net/item/detail/orig/photos/m\d+_\d+\.jpg', html)
    
    unique_images = set(images)
    unique_images2 = set([f"https://{x}" for x in images2])
    
    print("\nFound images:")
    for img in list(unique_images | unique_images2):
        print(f"  {img}")
        
    # Look for description
    descs = re.findall(r'"description":"([^"]+)"', html)
    print(f"\nFound descriptions (first 2):")
    for d in list(set(descs))[:2]:
        print(f"  {d[:150]}...")

extract_raw_data()
