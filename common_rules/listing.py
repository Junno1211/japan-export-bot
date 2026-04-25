"""
共通ルール層（管理部）— グループ2: 出品ルール。

Layer 3 部署で上書きできるルール: なし（本モジュールの定数・挙動は全部署固定）。
"""

from __future__ import annotations

from typing import Final

# ---- タイトル ---------------------------------------------------------------
TITLE_MAX_LENGTH: Final[int] = 80  # eBay タイトル最大文字数
REQUIRED_TITLE_SUFFIX: Final[str] = "SHIPPING WORLDWIDE"  # タイトル内必須文言（大文字小文字無視で検査）

# ---- 言語 -----------------------------------------------------------------
REQUIRED_LANGUAGES: Final[tuple[str, ...]] = ("en", "ja")  # 英語+日本語の両コンテンツが必須（has_both_languages）

# ---- 出力形式 ---------------------------------------------------------------
OUTPUT_FORMAT: Final[str] = "plain_text"  # プレーンテキスト（箱囲みなし）
SECTION_HEADER_PREFIX: Final[str] = "■"  # セクション見出し記号


def validate_title_length(title: str | None) -> bool:
    """タイトルが TITLE_MAX_LENGTH 字以内か。

    None は不正として False。空文字は長さ 0 として True。
    """
    if title is None:
        return False
    return len(title) <= TITLE_MAX_LENGTH


def has_required_suffix(title: str | None) -> bool:
    """タイトルに REQUIRED_TITLE_SUFFIX が含まれるか（大文字小文字を区別しない）。

    末尾である必要はなく、部分一致でよい（仕様上の「必須文言」検査）。
    """
    if title is None:
        return False
    return REQUIRED_TITLE_SUFFIX.lower() in title.lower()


def has_both_languages(content_en: str | None, content_ja: str | None) -> bool:
    """英語・日本語の説明（または同等フィールド）がともに非空か。

    言語判定は文字種ではなく、strip 後に文字が残るかのみ。
    """
    def _ok(s: str | None) -> bool:
        return bool(s and s.strip())

    return _ok(content_en) and _ok(content_ja)
