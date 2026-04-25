"""
共通ルール層（管理部）— 計算式・固定値の公開 API。
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

__all__ = [
    "ASSUMED_SHIPPING_JPY",
    "EXCHANGE_RATE_JPY_PER_USD",
    "FEE_BREAKDOWN",
    "MIN_PROFIT_JPY",
    "NET_RATE",
    "TAX_DIVISOR",
    "TAX_REFUND_RATE",
    "TOTAL_FEE_RATE",
    "calculate_profit_usd",
]
