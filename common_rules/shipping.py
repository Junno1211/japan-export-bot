"""
共通ルール層（管理部）— グループ3: 配送・運用ルール。

Layer 3 部署で上書きできるルール: なし（PROMOTED_LISTINGS_RATE 含め全部署固定）。
カテゴリ間の互換・禁止ペアは扱わない（混在検知は件数のみ）。
"""

from __future__ import annotations

from typing import Final

# ---- 配送 -----------------------------------------------------------------
SHIPPING_METHOD: Final[str] = "FedEx International"  # 固定
HANDLING_DAYS: Final[int] = 10  # Handling 期間（営業日）

# ---- Promoted Listings ----------------------------------------------------
PROMOTED_LISTINGS_RATE: Final[float] = 0.03  # 全 listing に 3%（部署では変更不可）

# ---- カテゴリ ---------------------------------------------------------------
DISALLOW_CATEGORY_MIXING: Final[bool] = True  # 1 出品で複数の主要カテゴリラベルを持たない


def validate_no_category_mixing(item_categories: list[str]) -> bool:
    """1 商品が複数の（空でない）主要カテゴリラベルを持っていないか。

    同一ラベルの重複は 1 種類とみなす。空文字・空白のみは無視する。
    カテゴリ名の意味（One Piece と Pokemon が別か等）は判定しない。
    """
    normalized: set[str] = set()
    for raw in item_categories:
        label = raw.strip()
        if label:
            normalized.add(label)
    return len(normalized) <= 1
