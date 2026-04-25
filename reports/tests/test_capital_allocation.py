"""Capital Allocation 層のテスト。"""

from __future__ import annotations

from reports.capital_allocation import (
    DepartmentMonthSnapshot,
    allocate_percentages,
    build_allocation_report,
    build_market_notes,
    decide_action,
    format_allocation_markdown,
    revenue_jpy,
)
from reports.generate_allocation_report import fetch_department_history
from reports.intelligence import DepartmentSummaryRow, TagRankingRow
from reports.ebay_data_fetcher import SoldLine
from reports.market_signals import ExchangeRateSignal, MarketSignalsReport, SeasonalitySignal, TrendSignal


def _market(change_pct: float | None = None, exchange_warning: bool = False) -> MarketSignalsReport:
    return MarketSignalsReport(
        report_date="2026-04-25",
        exchange_rate=ExchangeRateSignal(
            current_rate=152.3,
            configured_rate=155.0,
            deviation_pct=-1.7,
            warning=exchange_warning,
            history_30d=[],
        ),
        seasonality=SeasonalitySignal(month=4, status="データ不足", message="データ不足"),
        trend=TrendSignal(
            current_count=4,
            previous_3mo_average=None if change_pct is None else 3.0,
            change_pct=change_pct,
            judgement="データ不足" if change_pct is None else "通常",
        ),
    )


def test_revenue_jpy_uses_exchange_rate() -> None:
    assert revenue_jpy(100.0, 155.0) == 15_500


def test_allocate_percentages_by_revenue() -> None:
    rows = [
        DepartmentSummaryRow("A", 1, 100.0, 100.0),
        DepartmentSummaryRow("B", 1, 300.0, 300.0),
    ]
    assert allocate_percentages(rows) == {"A": 25, "B": 75}


def test_allocate_percentages_zero_revenue_even_split() -> None:
    rows = [
        DepartmentSummaryRow("A", 1, 0.0, 0.0),
        DepartmentSummaryRow("B", 1, 0.0, 0.0),
        DepartmentSummaryRow("C", 1, 0.0, 0.0),
    ]
    assert allocate_percentages(rows) == {"A": 34, "B": 33, "C": 33}


def test_decide_action_expand_candidate_high_price() -> None:
    row = DepartmentSummaryRow("Ohtani", 1, 864.0, 864.0)
    action, reason = decide_action(row, exchange_rate=155.0)
    assert action == "拡大候補(高単価)"
    assert "¥50K" in reason


def test_decide_action_increase_after_two_strong_months() -> None:
    row = DepartmentSummaryRow("One Piece", 40, 20.0, 800.0)
    history = [
        DepartmentMonthSnapshot("2026-04", 150_000, 35),
        DepartmentMonthSnapshot("2026-03", 120_000, 30),
    ]
    action, _ = decide_action(row, history=history)
    assert action == "増額"


def test_decide_action_exit_after_three_weak_months() -> None:
    row = DepartmentSummaryRow("Weak", 1, 10.0, 10.0)
    history = [
        DepartmentMonthSnapshot("2026-04", 10_000, 1),
        DepartmentMonthSnapshot("2026-03", 12_000, 1),
        DepartmentMonthSnapshot("2026-02", 18_000, 2),
    ]
    action, _ = decide_action(row, history=history)
    assert action == "撤退候補"


def test_decide_action_two_weak_months_not_exit_yet() -> None:
    row = DepartmentSummaryRow("Weak", 1, 10.0, 10.0)
    history = [
        DepartmentMonthSnapshot("2026-04", 10_000, 1),
        DepartmentMonthSnapshot("2026-03", 12_000, 1),
    ]
    action, _ = decide_action(row, history=history)
    assert action == "縮小"


def test_decide_action_data_insufficient_for_small_one_month() -> None:
    row = DepartmentSummaryRow("Tiny", 1, 50.0, 50.0)
    action, reason = decide_action(row, history=[])
    assert action == "データ不足"
    assert "件数不足" in reason


def test_build_market_notes() -> None:
    notes = build_market_notes(_market(change_pct=20.0))
    assert any("為替" in n for n in notes)
    assert any("当月件数" in n for n in notes)


def test_build_allocation_report_with_tag_note() -> None:
    rows = [DepartmentSummaryRow("Ohtani", 1, 864.0, 864.0)]
    tag_rankings = {"character": [TagRankingRow("character", "Shohei Ohtani", 864.0, 1)]}
    report = build_allocation_report(rows, tag_rankings=tag_rankings, market=_market(), month_label="2026年4月")
    assert report.recommendations[0].allocation_pct == 100
    assert report.recommendations[0].department == "Ohtani"
    assert any("上位キャラタグ" in n for n in report.notes)


def test_format_allocation_markdown() -> None:
    report = build_allocation_report(
        [DepartmentSummaryRow("Ohtani", 1, 864.0, 864.0)],
        market=_market(),
        month_label="2026年4月",
    )
    body = format_allocation_markdown(report)
    assert "# 2026年4月 Capital Allocation レポート" in body
    assert "| Ohtani |" in body
    assert "## 全体注意事項" in body


def test_empty_allocation_report() -> None:
    body = format_allocation_markdown(build_allocation_report([], month_label="2026年4月"))
    assert "(データなし)" in body


def test_fetch_department_history_includes_current_and_previous_month(monkeypatch) -> None:
    from reports.department_classifier import DepartmentProfile

    profiles = [DepartmentProfile("ohtani", "Ohtani", ("ohtani",), ())]
    current_rows = [DepartmentSummaryRow("Ohtani", 1, 100.0, 100.0)]

    def fake_fetch(_start, _end):
        return [SoldLine("p", "1", "Ohtani card", 50.0, "")]

    monkeypatch.setattr("reports.generate_allocation_report.fetch_completed_orders", fake_fetch)
    history = fetch_department_history(
        current_start_local=__import__("datetime").datetime(2026, 4, 1),
        current_rows=current_rows,
        profiles=profiles,
        months=2,
    )
    assert [s.month for s in history["Ohtani"]] == ["2026-04", "2026-03"]
