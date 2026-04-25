"""common_rules.shipping の単体テスト。"""

from __future__ import annotations

from common_rules.shipping import (
    DISALLOW_CATEGORY_MIXING,
    HANDLING_DAYS,
    PROMOTED_LISTINGS_RATE,
    SHIPPING_METHOD,
    validate_no_category_mixing,
)


class TestShippingConstants:
    def test_types_and_values(self) -> None:
        assert isinstance(SHIPPING_METHOD, str)
        assert SHIPPING_METHOD == "FedEx International"
        assert isinstance(HANDLING_DAYS, int)
        assert HANDLING_DAYS == 10
        assert isinstance(PROMOTED_LISTINGS_RATE, float)
        assert PROMOTED_LISTINGS_RATE == 0.03
        assert isinstance(DISALLOW_CATEGORY_MIXING, bool)
        assert DISALLOW_CATEGORY_MIXING is True


class TestValidateNoCategoryMixing:
    def test_single_category(self) -> None:
        assert validate_no_category_mixing(["Pokemon"]) is True
        assert validate_no_category_mixing(["One Piece"]) is True

    def test_same_label_duplicates(self) -> None:
        assert validate_no_category_mixing(["Pokemon", "Pokemon"]) is True

    def test_multiple_distinct_categories(self) -> None:
        assert validate_no_category_mixing(["One Piece", "Pokemon"]) is False

    def test_empty_and_blanks_ignored(self) -> None:
        assert validate_no_category_mixing(["", "  ", "Pokemon"]) is True
        assert validate_no_category_mixing([]) is True
