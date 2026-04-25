"""
共通ルール層（管理部）— 計算式・固定値・出品・配送・安全の公開 API。
"""

from common_rules.constants import (
    ASSUMED_SHIPPING_JPY,
    EXCHANGE_RATE_JPY_PER_USD,
    FEE_BREAKDOWN,
    MIN_PROFIT_JPY,
    NET_RATE,
    TAX_DIVISOR,
    TAX_REFUND_RATE,
    TOTAL_FEE_RATE,
)
from common_rules.financial import calculate_profit_usd
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
from common_rules.safety import MAX_CANCELLATION_RATE, is_cancellation_rate_safe
from common_rules.shipping import (
    DISALLOW_CATEGORY_MIXING,
    HANDLING_DAYS,
    PROMOTED_LISTINGS_RATE,
    SHIPPING_METHOD,
    validate_no_category_mixing,
)

__all__ = [
    "ASSUMED_SHIPPING_JPY",
    "DISALLOW_CATEGORY_MIXING",
    "EXCHANGE_RATE_JPY_PER_USD",
    "FEE_BREAKDOWN",
    "HANDLING_DAYS",
    "MAX_CANCELLATION_RATE",
    "MIN_PROFIT_JPY",
    "NET_RATE",
    "OUTPUT_FORMAT",
    "PROMOTED_LISTINGS_RATE",
    "REQUIRED_LANGUAGES",
    "REQUIRED_TITLE_SUFFIX",
    "SECTION_HEADER_PREFIX",
    "SHIPPING_METHOD",
    "TAX_DIVISOR",
    "TAX_REFUND_RATE",
    "TITLE_MAX_LENGTH",
    "TOTAL_FEE_RATE",
    "calculate_profit_usd",
    "has_both_languages",
    "has_required_suffix",
    "is_cancellation_rate_safe",
    "validate_no_category_mixing",
    "validate_title_length",
]
