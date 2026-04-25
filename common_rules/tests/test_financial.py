"""common_rules: 利益計算と定数の単体テスト。"""

from __future__ import annotations

import logging

import pytest

from common_rules.constants import (
    ASSUMED_SHIPPING_JPY,
    EXCHANGE_RATE_JPY_PER_USD,
    FEE_BREAKDOWN,
    MIN_PROFIT_JPY,
    NET_RATE,
    TAX_DIVISOR,
    TAX_REFUND_RATE,
    TOTAL_FEE_RATE,
    warn_if_fee_breakdown_mismatch,
)
from common_rules.financial import calculate_profit_usd


class TestCalculateProfitUsd:
    """仕様書・依頼書の式に沿った検証。

    利益(USD) = 売価(USD) × 0.804 − 仕入(JPY) ÷ 1.1 ÷ 155 − 送料(JPY) ÷ 155
    """

    def test_spec_formula_numeric_example(self) -> None:
        """代表例: 売価・仕入・送料を与えたとき、式どおりの USD 利益になる。"""
        sale_usd = 200.0
        cost_jpy = 11_000
        ship_jpy = 3_000
        expected = (
            sale_usd * 0.804
            - cost_jpy / 1.1 / 155.0
            - ship_jpy / 155.0
        )
        assert calculate_profit_usd(sale_usd, cost_jpy, ship_jpy) == pytest.approx(
            expected, rel=1e-12, abs=1e-9
        )

    def test_zero_cost_uses_sale_times_net_minus_shipping_over_fx(self) -> None:
        """仕入=0 のとき、売価×0.804 − 送料/155（既定送料3000）。"""
        sale_usd = 50.0
        expected = sale_usd * 0.804 - 3000.0 / 155.0
        assert calculate_profit_usd(sale_usd, 0.0) == pytest.approx(expected)

    def test_zero_sale_price_yields_negative_profit(self) -> None:
        """売価=0 のとき、コストと送料分だけマイナスになる。"""
        cost_jpy = 5_000
        ship_jpy = 3_000
        out = calculate_profit_usd(0.0, cost_jpy, ship_jpy)
        assert out < 0
        manual = -(cost_jpy / 1.1 / 155.0) - (ship_jpy / 155.0)
        assert out == pytest.approx(manual)

    def test_negative_arguments_raise_value_error(self) -> None:
        """負の引数は ValueError（0 は許容）。"""
        with pytest.raises(ValueError, match="0 以上"):
            calculate_profit_usd(-1.0, 0.0, 0.0)
        with pytest.raises(ValueError, match="0 以上"):
            calculate_profit_usd(10.0, -100.0, 0.0)
        with pytest.raises(ValueError, match="0 以上"):
            calculate_profit_usd(10.0, 100.0, -1.0)

    def test_zero_arguments_allowed(self) -> None:
        assert calculate_profit_usd(0.0, 0.0, 0.0) == pytest.approx(0.0)


class TestConstants:
    def test_fee_breakdown_sums_to_total_fee_rate(self) -> None:
        assert sum(FEE_BREAKDOWN.values()) == pytest.approx(TOTAL_FEE_RATE)

    def test_net_rate_matches_one_minus_total(self) -> None:
        assert NET_RATE == pytest.approx(1.0 - TOTAL_FEE_RATE)

    def test_tax_divisor(self) -> None:
        assert TAX_DIVISOR == pytest.approx(1.0 + TAX_REFUND_RATE)

    def test_types_and_values(self) -> None:
        assert isinstance(EXCHANGE_RATE_JPY_PER_USD, float)
        assert EXCHANGE_RATE_JPY_PER_USD == 155.0
        assert isinstance(TOTAL_FEE_RATE, float)
        assert TOTAL_FEE_RATE == 0.196
        assert isinstance(NET_RATE, float)
        assert isinstance(TAX_REFUND_RATE, float)
        assert TAX_REFUND_RATE == 0.10
        assert isinstance(MIN_PROFIT_JPY, int)
        assert MIN_PROFIT_JPY == 3000
        assert isinstance(ASSUMED_SHIPPING_JPY, int)
        assert ASSUMED_SHIPPING_JPY == 3000
        for k, v in FEE_BREAKDOWN.items():
            assert isinstance(k, str)
            assert isinstance(v, float)


class TestFeeMismatchWarning:
    def test_mismatch_logs_warning_only(self, caplog: pytest.LogCaptureFixture) -> None:
        """合計と TOTAL_FEE_RATE がずれると警告のみ（例外にしない）。"""
        caplog.set_level(logging.WARNING)
        log = logging.getLogger("test_fee_mismatch")
        warn_if_fee_breakdown_mismatch({"a": 0.1, "b": 0.2}, 0.196, _logger=log)
        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "WARNING"
