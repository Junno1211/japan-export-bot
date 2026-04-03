import json
from bs4 import BeautifulSoup

def analyze_html(filepath):
    print(f"Analyzing {filepath}...")
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script")
    
    found_json = False
    for i, script in enumerate(scripts):
        if not script.string:
            continue
            
        content = script.string.strip()
        # Look for typical Next.js or React state payloads
        if "id" in content and "status" in content or "price" in content:
            print(f"--- Script #{i} ---")
            snippet = content[:500] + ("..." if len(content)>500 else "")
            print(snippet)
            if "window.__" in content:
                print(f"  -> Found window.__ assignment in Script {i}")
            if "mercdn.net/item" in content:
                 print(f"  -> Found image links in Script {i}")
                 
    if not found_json:
        print("Done searching.")

analyze_html("debug_scrapingbee.html")
