"""商品タイトルから製品タグ（キャラ・状態・シリーズ・価格帯）を抽出する。"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TAG_DIR = Path(__file__).resolve().parent / "tags"


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("タグ辞書を読み込めません: %s (%s)", path, e)
        return None


def load_keyword_tags(path: Path) -> list[str]:
    data = _load_json(path)
    if not isinstance(data, list):
        return []
    return [str(x) for x in data if str(x).strip()]


def load_price_bands(path: Path) -> dict[str, tuple[float, float]]:
    data = _load_json(path)
    if not isinstance(data, dict):
        return {}

    bands: dict[str, tuple[float, float]] = {}
    for name, bounds in data.items():
        if not isinstance(bounds, list) or len(bounds) != 2:
            continue
        try:
            low = float(bounds[0])
            high = float(bounds[1])
        except (TypeError, ValueError):
            continue
        if str(name) == "premium":
            high = float("inf")
        bands[str(name)] = (low, high)
    return bands


def load_tag_dictionaries(tag_dir: Path = DEFAULT_TAG_DIR) -> dict[str, Any]:
    return {
        "character": load_keyword_tags(tag_dir / "characters.json"),
        "condition": load_keyword_tags(tag_dir / "conditions.json"),
        "series": load_keyword_tags(tag_dir / "series.json"),
        "price_band": load_price_bands(tag_dir / "price_bands.json"),
    }


def _match_keywords(title: str, keywords: list[str]) -> list[str]:
    haystack = (title or "").casefold()
    matched: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        k = keyword.strip()
        if not k:
            continue
        key = k.casefold()
        if _keyword_matches(haystack, key) and key not in seen:
            matched.append(k)
            seen.add(key)
    return matched


def _keyword_matches(haystack: str, keyword: str) -> bool:
    # 2文字程度の略語（NM/EXなど）は通常単語への誤爆が多いため境界付きで見る。
    if len(keyword) <= 2 and keyword.isalnum():
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", haystack) is not None
    return keyword in haystack


def _match_price_band(price_usd: float, bands: dict[str, tuple[float, float]]) -> list[str]:
    price = float(price_usd)
    for name, (low, high) in bands.items():
        if low <= price < high:
            return [name]
    return []


def tag_product(
    title: str,
    price_usd: float,
    *,
    tag_dir: Path = DEFAULT_TAG_DIR,
    dictionaries: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """英文タイトルと USD 価格からタグを抽出する。"""
    d = dictionaries if dictionaries is not None else load_tag_dictionaries(tag_dir)
    return {
        "character": _match_keywords(title, list(d.get("character") or [])),
        "condition": _match_keywords(title, list(d.get("condition") or [])),
        "series": _match_keywords(title, list(d.get("series") or [])),
        "price_band": _match_price_band(price_usd, dict(d.get("price_band") or {})),
    }
