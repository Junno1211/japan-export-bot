# -*- coding: utf-8 -*-
"""eBay 向けに検索価値のない「汎用トレカ」題名だけを検出する（improper 再送出の拒否・一括修復の対象判定）。"""

from __future__ import annotations

# 旧 auto_lister の _IMPROPER_GENERIC_TITLES（latinish_title_fallback の差し戻し）と同等のフレーズ。
# 空白を正規化し、小文字のトークン列全体が一致するときだけプレースホルダ扱いにする。
_LEGACY_EXACT_TOKEN_SEQS: frozenset[tuple[str, ...]] = frozenset(
    {
        tuple(s.split())
        for s in (
            "japanese collectible card",
            "japanese trading card collectible",
        )
    }
)


def is_placeholder_trading_card_title(title: str) -> bool:
    """
    汎用・ゴミ題名なら True。具体的なカード名が含まれる長い題名は False。

    - 空文字・空白のみは False（呼び元で「空」を別途判定する前提）
    - 「Japanese Collectible Card」等、語順・語数が legacy と一致するもののみ True
    """
    normalized = " ".join((title or "").strip().split())
    if not normalized:
        return False
    toks = tuple(normalized.casefold().split())
    return toks in _LEGACY_EXACT_TOKEN_SEQS
