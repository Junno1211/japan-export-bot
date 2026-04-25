"""
共通ルール層（管理部）— グループ4: 安全基準。

Layer 3 部署で上書きできるルール: なし（キャンセル率上限は全部署固定）。
"""

from __future__ import annotations

from typing import Final

# キャンセル率上限（超過はアカウントリスク — 閾値は未満を安全とみなす）
MAX_CANCELLATION_RATE: Final[float] = 0.05  # 5%


def is_cancellation_rate_safe(rate: float) -> bool:
    """キャンセル率が安全圏内か（MAX_CANCELLATION_RATE **未満**）。

    ちょうど 5.0% は安全ではない（上限に達している）。
    負の率は不正として False。
    """
    if rate < 0:
        return False
    return rate < MAX_CANCELLATION_RATE
