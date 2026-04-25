"""Market Signal 層の単体テスト。"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

from reports.generate_market_signals import fetch_monthly_sales_counts, main
from reports.market_signals import (
    FRANKFURTER_LATEST_URL,
    build_exchange_rate_signal,
    build_market_signals,
    build_seasonality_signal,
    build_trend_signal,
    calculate_deviation_pct,
    format_market_signals_markdown,
    parse_latest_usd_jpy,
    parse_series_usd_jpy,
    report_to_dict,
)


def test_calculate_exchange_deviation_pct() -> None:
    assert round(calculate_deviation_pct(152.3, 155.0), 1) == -1.7
    assert calculate_deviation_pct(162.75, 155.0) == 5.0


def test_exchange_warning_when_deviation_over_5_percent() -> None:
    def fetcher(url: str):
        if url == FRANKFURTER_LATEST_URL:
            return {"rates": {"JPY": 170.0}}
        return {"rates": {"2026-04-01": {"JPY": 160.0}}}

    signal = build_exchange_rate_signal(today=date(2026, 4, 25), configured_rate=155.0, fetcher=fetcher)
    assert signal.current_rate == 170.0
    assert signal.warning is True
    assert round(signal.deviation_pct or 0, 1) == 9.7


def test_exchange_api_error_is_graceful() -> None:
    def fetcher(_url: str):
        raise RuntimeError("network down")

    signal = build_exchange_rate_signal(today=date(2026, 4, 25), fetcher=fetcher)
    assert signal.current_rate is None
    assert signal.warning is False
    assert signal.error == "network down"


def test_exchange_series_error_preserves_current_rate() -> None:
    def fetcher(url: str):
        if url == FRANKFURTER_LATEST_URL:
            return {"rates": {"JPY": 152.3}}
        raise RuntimeError("series down")

    signal = build_exchange_rate_signal(today=date(2026, 4, 25), configured_rate=155.0, fetcher=fetcher)
    assert signal.current_rate == 152.3
    assert signal.deviation_pct is not None
    assert signal.history_30d == []
    assert "30日履歴取得失敗" in (signal.error or "")


def test_parse_latest_usd_jpy() -> None:
    assert parse_latest_usd_jpy({"rates": {"JPY": 152.3}}) == 152.3


def test_parse_series_usd_jpy_sorted() -> None:
    data = {"rates": {"2026-04-02": {"JPY": 152}, "2026-04-01": {"JPY": 151}}}
    assert parse_series_usd_jpy(data) == [("2026-04-01", 151.0), ("2026-04-02", 152.0)]


def test_seasonality_data_insufficient() -> None:
    signal = build_seasonality_signal(date(2026, 4, 25), {})
    assert signal.status == "データ不足"
    assert "不足" in signal.message


def test_seasonality_high_season() -> None:
    counts = {"2024-04": 20, "2025-04": 22, "2025-01": 5, "2025-02": 5, "2025-03": 5}
    signal = build_seasonality_signal(date(2026, 4, 25), counts)
    assert signal.status == "ハイシーズン"
    assert signal.relative_to_annual_pct is not None
    assert signal.relative_to_annual_pct > 10


def test_seasonality_excludes_current_partial_month_from_annual_average() -> None:
    counts = {"2026-04": 1, "2025-04": 20, "2026-03": 10, "2026-02": 10}
    signal = build_seasonality_signal(date(2026, 4, 25), counts)
    assert signal.annual_average_count == 40 / 3


def test_trend_data_insufficient() -> None:
    signal = build_trend_signal(date(2026, 4, 25), {"2026-04": 4})
    assert signal.judgement == "データ不足"
    assert signal.previous_3mo_average is None


def test_trend_surge_detection() -> None:
    counts = {"2026-04": 40, "2026-03": 20, "2026-02": 20, "2026-01": 20}
    signal = build_trend_signal(date(2026, 4, 25), counts)
    assert signal.judgement == "急増"
    assert signal.change_pct == 100.0


def test_trend_drop_detection() -> None:
    counts = {"2026-04": 10, "2026-03": 20, "2026-02": 20, "2026-01": 20}
    signal = build_trend_signal(date(2026, 4, 25), counts)
    assert signal.judgement == "急減"
    assert signal.change_pct == -50.0


def test_markdown_output_format() -> None:
    report = build_market_signals(
        today=date(2026, 4, 25),
        monthly_counts={"2026-04": 4},
        fetcher=lambda _url: {"rates": {"JPY": 152.3}},
    )
    body = format_market_signals_markdown(report)
    assert "# Market Signals - 2026-04-25" in body
    assert "## 為替レート(JPY/USD)" in body
    assert "## 季節要因" in body
    assert "## トレンド検出" in body


def test_json_output_format() -> None:
    report = build_market_signals(today=date(2026, 4, 25), fetcher=lambda _url: {"rates": {"JPY": 152.3}})
    data = report_to_dict(report)
    assert data["report_date"] == "2026-04-25"
    assert "exchange_rate" in data
    json.dumps(data, ensure_ascii=False)


def test_cli_writes_markdown_and_json(tmp_path, capsys) -> None:
    with patch("reports.generate_market_signals.ROOT", tmp_path):
        with patch("reports.generate_market_signals.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 25)
            with patch(
                "reports.generate_market_signals.build_market_signals",
                return_value=build_market_signals(today=date(2026, 4, 25), fetcher=lambda _url: {"rates": {"JPY": 152.3}}),
            ):
                with patch("reports.generate_market_signals.fetch_monthly_sales_counts", return_value={}):
                    main(["--json"])
    out = capsys.readouterr().out
    assert "Markdown 保存" in out
    assert "JSON 保存" in out
    assert (tmp_path / "reports" / "output" / "market_signals_2026-04-25.md").exists()
    assert (tmp_path / "reports" / "output" / "market_signals_2026-04-25.json").exists()


def test_fetch_monthly_sales_counts_uses_current_and_previous_three_months() -> None:
    calls = []

    def fake_fetch(start, end):
        calls.append((start, end))
        return [object(), object()]

    with patch("reports.generate_market_signals.fetch_completed_orders", side_effect=fake_fetch):
        counts = fetch_monthly_sales_counts(date(2026, 4, 25))

    assert counts == {"2026-04": 2, "2026-03": 2, "2026-02": 2, "2026-01": 2}
    assert len(calls) == 4
