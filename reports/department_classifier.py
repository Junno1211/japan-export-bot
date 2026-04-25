"""
部署判定: sourcing/<部署>/keywords.json のキーワードと eBay タイトル（小文字）の一致数でスコア。
複数部署で最大スコアが同点のときはフォルダ名の辞書順で先の部署を採用。
いずれの部署もスコアが 0 なら「未分類」。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# レポート列に使う表示名（フォルダ名 → 短い英語ラベル）
_DISPLAY_NAME_BY_FOLDER: dict[str, str] = {
    "onepiece": "One Piece",
    "pokemon": "Pokemon",
    "ohtani": "Ohtani",
    "dragonball": "Dragon Ball",
    "bikkuriman": "Bikkuriman",
    "bbm_baseball": "BBM Baseball",
    "bbm_mlb_japan": "BBM MLB Japan",
    "bbm_sumo": "BBM Sumo",
}

_UNCLASSIFIED = "未分類"


@dataclass(frozen=True)
class DepartmentProfile:
    """1 部署分のキーワード集合。"""

    folder: str
    display_name: str
    keywords: tuple[str, ...]
    ng_keywords: tuple[str, ...]


def _normalize_kw(s: str) -> str:
    return (s or "").strip().lower()


def _collect_keyword_strings(data: dict) -> list[str]:
    out: list[str] = []
    for key in ("card_keywords", "ebay_keywords", "mercari_keywords"):
        raw = data.get(key)
        if isinstance(raw, list):
            for x in raw:
                if isinstance(x, str) and x.strip():
                    out.append(x.strip())
    return out


def load_department_profiles(sourcing_dir: Path) -> list[DepartmentProfile]:
    """sourcing/ 直下の各フォルダで keywords.json があれば部署として読み込む。"""
    profiles: list[DepartmentProfile] = []
    if not sourcing_dir.is_dir():
        return profiles

    for child in sorted(sourcing_dir.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        kw_path = child / "keywords.json"
        if not kw_path.is_file():
            continue
        try:
            with kw_path.open(encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        folder = child.name
        display = _DISPLAY_NAME_BY_FOLDER.get(folder, folder.replace("_", " ").title())
        kws = tuple(_normalize_kw(x) for x in _collect_keyword_strings(data) if _normalize_kw(x))
        ng_raw = data.get("ng_keywords")
        ng_list: list[str] = []
        if isinstance(ng_raw, list):
            for x in ng_raw:
                if isinstance(x, str) and _normalize_kw(x):
                    ng_list.append(_normalize_kw(x))
        ng_t = tuple(ng_list)
        if not kws and not ng_t:
            continue
        profiles.append(
            DepartmentProfile(
                folder=folder,
                display_name=display,
                keywords=kws,
                ng_keywords=ng_t,
            )
        )
    return profiles


def _title_violates_ng(title_lower: str, ng: Iterable[str]) -> bool:
    return any(ng_kw in title_lower for ng_kw in ng)


def score_department(title_lower: str, profile: DepartmentProfile) -> int:
    """タイトルに含まれるキーワード数（重複キーワードは 1 回ずつカウント）。"""
    if _title_violates_ng(title_lower, profile.ng_keywords):
        return 0
    score = 0
    for kw in profile.keywords:
        if not kw:
            continue
        if kw in title_lower:
            score += 1
    return score


def classify_title(title: str, profiles: list[DepartmentProfile]) -> tuple[str, str]:
    """
    Returns:
        (internal_key, display_label) — internal_key は folder 名または _UNCLASSIFIED。
    """
    title_lower = (title or "").lower()
    best_score = -1
    best: list[DepartmentProfile] = []
    for p in profiles:
        s = score_department(title_lower, p)
        if s > best_score:
            best_score = s
            best = [p]
        elif s == best_score and s > 0:
            best.append(p)

    if best_score <= 0 or not best:
        return (_UNCLASSIFIED, _UNCLASSIFIED)

    best_sorted = sorted(best, key=lambda x: x.folder.lower())
    chosen = best_sorted[0]
    return (chosen.folder, chosen.display_name)
