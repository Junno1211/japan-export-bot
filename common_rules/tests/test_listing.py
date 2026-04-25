"""common_rules.listing の単体テスト。"""

from __future__ import annotations

from common_rules.listing import (
    OUTPUT_FORMAT,
    REQUIRED_LANGUAGES,
    REQUIRED_TITLE_SUFFIX,
    SECTION_HEADER_PREFIX,
    TITLE_MAX_LENGTH,
    has_both_languages,
    has_required_suffix,
    validate_title_length,
)


class TestValidateTitleLength:
    def test_within_limit(self) -> None:
        assert validate_title_length("a" * 80) is True
        assert validate_title_length("") is True

    def test_exceeds_limit(self) -> None:
        assert validate_title_length("x" * 81) is False

    def test_none(self) -> None:
        assert validate_title_length(None) is False


class TestHasRequiredSuffix:
    def test_contains_required(self) -> None:
        t = f"Pokemon Card {REQUIRED_TITLE_SUFFIX}"
        assert has_required_suffix(t) is True

    def test_missing(self) -> None:
        assert has_required_suffix("Pokemon Card Only") is False

    def test_lowercase_variant(self) -> None:
        assert has_required_suffix("foo shipping worldwide bar") is True

    def test_not_only_at_end(self) -> None:
        mid = f"XX {REQUIRED_TITLE_SUFFIX} YY"
        assert has_required_suffix(mid) is True

    def test_none(self) -> None:
        assert has_required_suffix(None) is False


class TestHasBothLanguages:
    def test_both_present(self) -> None:
        assert has_both_languages("Hello", "こんにちは") is True

    def test_english_only(self) -> None:
        assert has_both_languages("Hello only", None) is False

    def test_japanese_only(self) -> None:
        assert has_both_languages(None, "日本語だけ") is False

    def test_both_none(self) -> None:
        assert has_both_languages(None, None) is False

    def test_whitespace_only_is_absent(self) -> None:
        assert has_both_languages("   ", "本文") is False


class TestListingConstants:
    def test_types_and_values(self) -> None:
        assert TITLE_MAX_LENGTH == 80
        assert REQUIRED_TITLE_SUFFIX == "SHIPPING WORLDWIDE"
        assert REQUIRED_LANGUAGES == ("en", "ja")
        assert OUTPUT_FORMAT == "plain_text"
        assert SECTION_HEADER_PREFIX == "■"
