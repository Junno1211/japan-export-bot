"""
共通ルール層（管理部）— 利益などの計算式。

式の係数は common_rules.constants と一致させる（単一の正本）。
"""

from __future__ import annotations

from common_rules.constants import (
    ASSUMED_SHIPPING_JPY,
    EXCHANGE_RATE_JPY_PER_USD,
    NET_RATE,
    TAX_DIVISOR,
)


def calculate_profit_usd(
    sale_price_usd: float,
    cost_jpy: float,
    shipping_jpy: float = ASSUMED_SHIPPING_JPY,
) -> float:
    """利益を USD で計算する。

    利益(USD) = 売価(USD) × NET_RATE − 仕入(JPY) ÷ TAX_DIVISOR ÷ 為替 − 送料(JPY) ÷ 為替

    仕様書の数式表記: 売価 × 0.804 − 仕入 ÷ 1.1 ÷ 155 − 送料 ÷ 155

    Args:
        sale_price_usd: eBay 売価（USD）。負数は許容しない。
        cost_jpy: 仕入（税込円）。負数は許容しない。
        shipping_jpy: 送料想定（円）。省略時は全社共通 ASSUMED_SHIPPING_JPY。
            Layer 3 部署層で上書き可能（将来）。

    Returns:
        推定利益（USD）。

    Raises:
        ValueError: sale_price_usd / cost_jpy / shipping_jpy のいずれかが負のとき。
    """
    if sale_price_usd < 0 or cost_jpy < 0 or shipping_jpy < 0:
        raise ValueError(
            "sale_price_usd, cost_jpy, shipping_jpy はいずれも 0 以上である必要があります。"
        )
    return (
        sale_price_usd * NET_RATE
        - (cost_jpy / TAX_DIVISOR) / EXCHANGE_RATE_JPY_PER_USD
        - shipping_jpy / EXCHANGE_RATE_JPY_PER_USD
    )
