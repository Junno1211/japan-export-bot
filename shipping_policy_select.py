# -*- coding: utf-8 -*-
"""
送料ビジネスポリシー（価格帯 band）の唯一の決定経路。
近い band へのフォールバックは禁止（赤字・表示不整合の原因）。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Tuple

from config import SHIPPING_POLICY_MAP, LISTING_MAX_PRICE_USD

_log = logging.getLogger(__name__)
_MAP_VALIDATED = False


class ShippingBandNotConfiguredError(RuntimeError):
    """SHIPPING_POLICY_MAP に該当ブラケットの Profile ID が未登録。"""


class ShippingBandMismatchError(AssertionError):
    """価格が policy 名が表す band に収まらない。"""


@dataclass(frozen=True)
class ShippingPolicySelection:
    """select_shipping_policy の戻り値（ID は Trading API 用、policy_name は検証・ログ用）。"""

    policy_id: str
    policy_name: str
    band_lower_usd: float
    band_upper_usd: float
    bracket_key: int


def compute_bracket_key(item_price_usd: float) -> int:
    """auto_lister 従来どおりの $50 刻み（$100 未満はキー 0）。"""
    p = float(item_price_usd)
    if p < 0:
        raise ValueError(f"item_price_usd must be >= 0, got {p}")
    if p < 100:
        return 0
    return int((p - 100) // 50) * 50 + 100


def bracket_key_to_band_bounds(bracket_key: int) -> Tuple[float, float]:
    """band の USD 下限・上限（いずれも端点含む）。"""
    if bracket_key == 0:
        return 0.0, 99.99
    return float(bracket_key), float(bracket_key) + 49.99


def policy_label_for_bracket(bracket_key: int) -> str:
    if bracket_key == 0:
        return "$0–$99"
    lo_i = int(bracket_key)
    hi_i = int(bracket_key + 49)
    return f"${lo_i:,}–${hi_i:,}"


_BAND_NAME_RE = re.compile(
    r"\$\s*([0-9][0-9,]*)\s*[–\-]\s*\$?\s*([0-9][0-9,]*)",
    re.UNICODE,
)


def parse_band_from_policy_name(shipping_policy_name: str) -> Tuple[float, float]:
    """
    policy 表示名から band 下限・上限（USD）を取り出す。
    例: \"$1,750–$1,799\" → (1750.0, 1799.99)
    ハイフン・en dash 両対応。上限は整数表示を 49.99 セント刻みの帯として解釈。
    """
    s = (shipping_policy_name or "").strip()
    m = _BAND_NAME_RE.search(s)
    if not m:
        raise ValueError(f"Unrecognized shipping policy band name: {shipping_policy_name!r}")
    lo = float(m.group(1).replace(",", ""))
    hi_int = float(m.group(2).replace(",", ""))
    # \"$850–$899\" のような整数上限 → そのキーの band 上限は *.99
    upper = hi_int + 0.99 if abs(hi_int - round(hi_int)) < 1e-9 else float(m.group(2).replace(",", ""))
    return lo, upper


def assert_shipping_band_matches_price(item_price_usd: float, shipping_policy_name: str) -> None:
    lower, upper = parse_band_from_policy_name(shipping_policy_name)
    p = float(item_price_usd)
    if not (lower <= p <= upper):
        raise ShippingBandMismatchError(
            f"SHIPPING BAND MISMATCH: price=${p}, band=${lower:g}–${upper:g}, policy={shipping_policy_name!r}"
        )


def iter_required_bracket_keys(max_listing_usd: float | None = None) -> list[int]:
    """出品上限価格までに必要な全 bracket_key（test_rules 完全性チェック用）。"""
    cap = float(max_listing_usd if max_listing_usd is not None else LISTING_MAX_PRICE_USD)
    keys = [0]
    k = 100
    max_key = compute_bracket_key(cap)
    while k <= max_key:
        keys.append(k)
        k += 50
    return keys


def collect_shipping_policy_map_issues() -> list[str]:
    """
    SHIPPING_POLICY_MAP の欠落・空 ID・非数値を ERROR、同一 Profile ID の複数 band を WARNING で列挙する。
    """
    issues: list[str] = []
    keys = iter_required_bracket_keys(LISTING_MAX_PRICE_USD)
    dup_track: dict[str, list[int]] = {}
    for k in keys:
        raw = SHIPPING_POLICY_MAP.get(k)
        if raw is None:
            lo, hi = bracket_key_to_band_bounds(k)
            issues.append(
                f"ERROR: missing bracket_key={k} (${lo:g}–${hi:g}) in SHIPPING_POLICY_MAP"
            )
            continue
        pid = str(raw).strip()
        if not pid:
            lo, hi = bracket_key_to_band_bounds(k)
            issues.append(
                f"ERROR: empty Shipping Profile ID for bracket_key={k} (${lo:g}–${hi:g})"
            )
        elif not pid.isdigit():
            issues.append(f"ERROR: non-numeric Shipping Profile ID for key {k}: {pid!r}")
        else:
            dup_track.setdefault(pid, []).append(k)
    for pid, ks in sorted(dup_track.items(), key=lambda x: x[0]):
        if len(ks) > 1:
            issues.append(
                "WARNING: duplicate eBay Shipping Profile ID "
                f"{pid} for bracket_keys={ks} — verify Seller Hub bands / config._SHIPPING_POLICY_BASE"
            )
    return issues


def ensure_shipping_policy_map_complete() -> None:
    """初回出品または初回 select 時にマップを検証（ERROR なら例外、WARNING はログ）。"""
    global _MAP_VALIDATED
    if _MAP_VALIDATED:
        return
    msgs = collect_shipping_policy_map_issues()
    errors = [m for m in msgs if m.startswith("ERROR:")]
    if errors:
        raise ShippingBandNotConfiguredError(
            "Shipping policy map check failed:\n" + "\n".join(errors)
        )
    for m in msgs:
        if m.startswith("WARNING:"):
            _log.warning("%s", m)
    _MAP_VALIDATED = True


def select_shipping_policy(item_price_usd: float) -> ShippingPolicySelection:
    """
    商品価格に属する band の Shipping Profile ID を返す（唯一の決定経路）。
    マップ欠落・空 ID は例外で停止する。
    """
    ensure_shipping_policy_map_complete()
    p = float(item_price_usd)
    if p > float(LISTING_MAX_PRICE_USD):
        raise ValueError(
            f"item_price_usd ${p} exceeds LISTING_MAX_PRICE_USD ${LISTING_MAX_PRICE_USD}"
        )
    key = compute_bracket_key(p)
    raw = SHIPPING_POLICY_MAP.get(key)
    if raw is None or not str(raw).strip():
        lo, hi = bracket_key_to_band_bounds(key)
        raise ShippingBandNotConfiguredError(
            f"SHIPPING_POLICY_MAP に bracket_key={key} (${lo:g}–${hi:g}) の eBay Shipping Profile ID が未設定です。"
            f" Seller Hub の該当 band の ID を config.SHIPPING_POLICY_MAP[{key}] に追加してください。"
        )
    policy_id = str(raw).strip()
    if not policy_id.isdigit():
        raise ShippingBandNotConfiguredError(
            f"SHIPPING_POLICY_MAP[{key}] must be numeric profile id, got {policy_id!r}"
        )
    blo, bhi = bracket_key_to_band_bounds(key)
    name = policy_label_for_bracket(key)
    if not (blo <= p <= bhi):
        raise ShippingBandMismatchError(
            f"INTERNAL: price ${p} not in bracket bounds [{blo}, {bhi}] for key {key}"
        )
    assert_shipping_band_matches_price(p, name)
    return ShippingPolicySelection(
        policy_id=policy_id,
        policy_name=name,
        band_lower_usd=blo,
        band_upper_usd=bhi,
        bracket_key=key,
    )


def select_shipping_policy_id(item_price_usd: float) -> str:
    return select_shipping_policy(item_price_usd).policy_id
