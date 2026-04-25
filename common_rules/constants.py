"""
共通ルール層（管理部）— 為替・手数料・税率などの固定値。

Layer 3 部署層では MIN_PROFIT_JPY / ASSUMED_SHIPPING_JPY 等を上書き可能（将来）。
"""

from __future__ import annotations

import logging
from typing import Final

logger = logging.getLogger(__name__)

# ---- 為替 -----------------------------------------------------------------
EXCHANGE_RATE_JPY_PER_USD: Final[float] = 155.0  # 固定値（JPY per USD）

# ---- 手数料（合計率とネット率）---------------------------------------------
TOTAL_FEE_RATE: Final[float] = 0.196  # 固定値
NET_RATE: Final[float] = 1.0 - TOTAL_FEE_RATE  # 0.804

# 参照用（計算ロジックでは NET_RATE / TOTAL_FEE_RATE を使用）
FEE_BREAKDOWN: Final[dict[str, float]] = {
    "fvf": 0.1325,  # eBay Final Value Fee
    "international": 0.0135,  # 国際取引手数料
    "payoneer": 0.02,  # Payoneer 受取手数料
    "promoted": 0.03,  # Promoted Listings 標準率
}

# ---- 消費税還付（仕入税込を除税する係数）---------------------------------
TAX_REFUND_RATE: Final[float] = 0.10  # 固定値
TAX_DIVISOR: Final[float] = 1.0 + TAX_REFUND_RATE  # 1.10

# ---- 全社ガード（Layer 3 で上書き可能・将来）-----------------------------
MIN_PROFIT_JPY: Final[int] = 3000  # 全社共通の最低利益下限（円）
ASSUMED_SHIPPING_JPY: Final[int] = 3000  # 全社共通の最低送料想定（円）


def warn_if_fee_breakdown_mismatch(
    breakdown: dict[str, float],
    total_fee_rate: float,
    *,
    _logger: logging.Logger | None = None,
) -> None:
    """FEE_BREAKDOWN の合計と TOTAL_FEE_RATE の整合性を検査し、ずれていれば警告する。"""
    log = _logger if _logger is not None else logger
    total = sum(breakdown.values())
    if abs(total - total_fee_rate) > 1e-9:
        log.warning(
            "FEE_BREAKDOWN の合計 (%.6f) が TOTAL_FEE_RATE (%.6f) と一致しません。"
            " 定数の見直しが必要です。",
            total,
            total_fee_rate,
        )


warn_if_fee_breakdown_mismatch(FEE_BREAKDOWN, TOTAL_FEE_RATE)
