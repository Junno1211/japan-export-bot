"""report_generator の集計・出力テスト。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from common_rules import EXCHANGE_RATE_JPY_PER_USD

from reports.department_classifier import DepartmentProfile
from reports.ebay_data_fetcher import SoldLine
from reports.report_generator import (
    aggregate_sales_by_department,
    aggregate_sales_by_tags,
    build_total_row,
    format_terminal_table,
    month_range_tokyo,
    write_markdown_report,
)


def _profiles() -> list[DepartmentProfile]:
    return [
        DepartmentProfile(
            folder="alpha",
            display_name="AlphaDept",
            keywords=("onepiece", "alpha"),
            ng_keywords=(),
        ),
        DepartmentProfile(
            folder="beta",
            display_name="BetaDept",
            keywords=("pokemon",),
            ng_keywords=(),
        ),
    ]


def test_aggregate_revenue_by_department() -> None:
    lines = [
        SoldLine("o1", "1", "OnePiece rare", 100.0, ""),
        SoldLine("o2", "2", "OnePiece common", 50.0, ""),
        SoldLine("o3", "3", "Pokemon card", 200.0, ""),
    ]
    rows, meta = aggregate_sales_by_department(lines, _profiles(), {})
    by_name = {r.display_name: r for r in rows}
    assert by_name["AlphaDept"].revenue_usd == 150.0
    assert by_name["AlphaDept"].count == 2
    assert by_name["BetaDept"].revenue_usd == 200.0
    assert meta["profits_enabled"] is False


def test_aggregate_with_full_costs_computes_profit() -> None:
    lines = [
        SoldLine("o1", "1", "OnePiece rare", 100.0, ""),
        SoldLine("o2", "2", "OnePiece common", 50.0, ""),
    ]
    cost = {"1": 5000, "2": 3000}
    rows, meta = aggregate_sales_by_department(lines, _profiles(), cost)
    assert meta["profits_enabled"] is True
    r = next(x for x in rows if x.display_name == "AlphaDept")
    assert r.total_profit_jpy is not None
    assert r.avg_profit_jpy is not None
    assert r.count == 2


def test_month_range_tokyo_starts_first_day() -> None:
    tz = ZoneInfo("Asia/Tokyo")
    fixed = datetime(2026, 4, 25, 14, 0, tzinfo=tz)
    start, end = month_range_tokyo(fixed)
    assert start.day == 1 and start.month == 4
    assert end.day == 25


def test_terminal_and_markdown_smoke(tmp_path) -> None:
    lines = [SoldLine("o", "1", "OnePiece x", 10.0, "")]
    rows, meta = aggregate_sales_by_department(lines, _profiles(), {})
    total = build_total_row(rows)
    txt = format_terminal_table(2026, 4, 1, 25, rows, total_row=total)
    assert "OnePiece" in lines[0].title or "AlphaDept" in txt
    assert "売上(USD)" in txt
    md = tmp_path / "out.md"
    write_markdown_report(
        md,
        2026,
        4,
        "2026-04-01",
        "2026-04-25 14:00",
        rows,
        total,
        unclassified_count=int(meta["unclassified_count"]),
        profits_enabled=False,
    )
    body = md.read_text(encoding="utf-8")
    assert "部署別売上" in body
    assert "AlphaDept" in body


def test_revenue_jpy_uses_common_rules_rate() -> None:
    lines = [SoldLine("o", "1", "OnePiece x", 1.0, "")]
    rows, _ = aggregate_sales_by_department(lines, _profiles(), {})
    r = rows[0]
    assert r.revenue_jpy == int(round(1.0 * EXCHANGE_RATE_JPY_PER_USD))


def test_aggregate_sales_by_tags() -> None:
    lines = [
        SoldLine("o1", "1", "Shohei Ohtani BBM 2024 PSA10", 864.0, ""),
        SoldLine("o2", "2", "One Piece Carddass Luffy Mint", 200.0, ""),
        SoldLine("o3", "3", "Unknown item", 50.0, ""),
    ]
    tags = aggregate_sales_by_tags(lines)
    chars = {r.tag: r for r in tags["character"]}
    assert chars["Ohtani"].revenue_usd == 864.0
    assert chars["Luffy"].count == 1
    assert chars["(該当なし)"].revenue_usd == 50.0
    bands = {r.tag: r for r in tags["price_band"]}
    assert bands["<$100"].count == 1
    assert bands["$100-$300"].count == 1
    assert bands["$300-$1000"].count == 1
    assert bands["$1000+"].count == 0


def test_terminal_output_includes_tag_sections() -> None:
    lines = [SoldLine("o1", "1", "Shohei Ohtani BBM 2024 PSA10", 864.0, "")]
    rows, _ = aggregate_sales_by_department(lines, _profiles(), {})
    tags = aggregate_sales_by_tags(lines)
    txt = format_terminal_table(2026, 4, 1, 25, rows, total_row=build_total_row(rows), tag_sections=tags)
    assert "## キャラ別" in txt
    assert "Ohtani" in txt
    assert "$300-$1000" in txt


def test_markdown_report_includes_tag_sections(tmp_path) -> None:
    lines = [SoldLine("o1", "1", "Pikachu Pokemon Carddass Near Mint", 150.0, "")]
    rows, meta = aggregate_sales_by_department(lines, _profiles(), {})
    tags = aggregate_sales_by_tags(lines)
    md = tmp_path / "tags.md"
    write_markdown_report(
        md,
        2026,
        4,
        "2026-04-01",
        "2026-04-25 14:00",
        rows,
        build_total_row(rows),
        unclassified_count=int(meta["unclassified_count"]),
        profits_enabled=False,
        tag_sections=tags,
    )
    body = md.read_text(encoding="utf-8")
    assert "## キャラ別" in body
    assert "| Pikachu | 150 | 1 |" in body
    assert "## 価格帯別" in body
