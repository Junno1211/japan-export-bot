import os
import requests
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Notion Configuration
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
DATABASE_ID_KEYWORDS = os.getenv("NOTION_DATABASE_ID_KEYWORDS", "")
DATABASE_ID_CONFIG = os.getenv("NOTION_DATABASE_ID_CONFIG", "")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def fetch_notion_keywords() -> List[str]:
    """
    Notionの「キーワード一覧」データベースからアクティブな検索語句を取得します。
    """
    if not NOTION_TOKEN or not DATABASE_ID_KEYWORDS:
        logger.warning("Notion API Token or Database ID is missing. Skipping Notion sync.")
        return []

    url = f"https://api.notion.com/v1/databases/{DATABASE_ID_KEYWORDS}/query"
    try:
        response = requests.post(url, headers=HEADERS, json={
            "filter": {
                "property": "Status",
                "select": {
                    "equals": "Active"
                }
            }
        })
        response.raise_for_status()
        data = response.json()
        
        keywords = []
        for result in data.get("results", []):
            properties = result.get("properties", {})
            # 「Name」プロパティ（タイトル型）からテキストを抽出
            name_prop = properties.get("Name", {}).get("title", [])
            if name_prop:
                keywords.append(name_prop[0]["plain_text"])
        
        return keywords
    except Exception as e:
        logger.error(f"Failed to fetch keywords from Notion: {e}")
        return []

def fetch_notion_config() -> Dict[str, Any]:
    """
    Notionの「システム設定」データベースからグローバル設定を取得します。
    """
    if not NOTION_TOKEN or not DATABASE_ID_CONFIG:
        return {}

    url = f"https://api.notion.com/v1/databases/{DATABASE_ID_CONFIG}/query"
    try:
        response = requests.post(url, headers=HEADERS)
        response.raise_for_status()
        data = response.json()
        
        config = {}
        for result in data.get("results", []):
            properties = result.get("properties", {})
            key = properties.get("Key", {}).get("title", [{}])[0].get("plain_text")
            value = properties.get("Value", {}).get("number") or properties.get("Value", {}).get("rich_text", [{}])[0].get("plain_text")
            if key:
                config[key] = value
        
        return config
    except Exception as e:
        logger.error(f"Failed to fetch config from Notion: {e}")
        return {}

if __name__ == "__main__":
    # Test Debug
    logging.basicConfig(level=logging.INFO)
    print("Testing Notion Fetch...")
    print(f"Keywords: {fetch_notion_keywords()}")
    print(f"Config: {fetch_notion_config()}")
