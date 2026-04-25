"""Intelligence 層の集計テスト。"""

from __future__ import annotations

from datetime import datetime

from reports.department_classifier import DepartmentProfile
from reports.ebay_data_fetcher import SoldLine
from reports.intelligence import (
    build_cross_rankings,
    build_department_summary,
    build_intelligence_report,
    build_monthly_trends,
    build_tag_rankings,
    format_intelligence_markdown,
    month_label_from_date,
)


def _profiles() -> list[DepartmentProfile]:
    return [
        DepartmentProfile("ohtani", "Ohtani", ("ohtani",), ()),
        DepartmentProfile("onepiece", "One Piece", ("luffy", "zoro", "one piece"), ()),
        DepartmentProfile("pokemon", "Pokemon", ("pikachu", "pokemon"), ()),
    ]


def _dicts() -> dict:
    return {
        "character": ["Ohtani", "Shohei Ohtani", "Luffy", "Zoro", "Pikachu"],
        "condition": ["PSA10", "PSA 10", "Mint", "Near Mint", "Holo"],
        "series": ["BBM 2024", "Pokemon Carddass", "One Piece Carddass"],
        "price_band": {
            "low": (0.0, 100.0),
            "mid": (100.0, 300.0),
            "high": (300.0, 1000.0),
            "premium": (1000.0, float("inf")),
        },
    }


def _lines() -> list[SoldLine]:
    return [
        SoldLine("o1", "1", "Shohei Ohtani BBM 2024 PSA10", 864.0, ""),
        SoldLine("o2", "2", "Luffy One Piece Carddass Holo", 274.0, ""),
        SoldLine("o3", "3", "Luffy Mint card", 131.0, ""),
        SoldLine("o4", "4", "Pikachu Pokemon Carddass Near Mint", 90.0, ""),
        SoldLine("o5", "5", "Unknown item", 20.0, ""),
    ]


def test_tag_ranking_character_top5() -> None:
    rankings = build_tag_rankings(_lines(), dictionaries=_dicts())
    chars = rankings["character"]
    assert chars[0].tag == "Shohei Ohtani"
    assert chars[0].revenue_usd == 864.0
    assert chars[1].tag == "Luffy"
    assert chars[1].count == 2


def test_tag_ranking_uses_canonical_specific_tag() -> None:
    rankings = build_tag_rankings(_lines()[:1], dictionaries=_dicts())
    tags = [r.tag for r in rankings["character"]]
    assert tags == ["Shohei Ohtani"]


def test_condition_ranking() -> None:
    rankings = build_tag_rankings(_lines(), dictionaries=_dicts())
    conditions = {r.tag: r for r in rankings["condition"]}
    assert conditions["PSA10"].revenue_usd == 864.0
    assert conditions["Holo"].count == 1


def test_series_ranking() -> None:
    rankings = build_tag_rankings(_lines(), dictionaries=_dicts())
    series = {r.tag: r for r in rankings["series"]}
    assert series["BBM 2024"].count == 1
    assert series["One Piece Carddass"].revenue_usd == 274.0


def test_price_band_ranking() -> None:
    rankings = build_tag_rankings(_lines(), dictionaries=_dicts())
    bands = {r.tag: r for r in rankings["price_band"]}
    assert bands["$300-$1000"].revenue_usd == 864.0
    assert bands["<$100"].count == 2


def test_cross_character_condition_top10() -> None:
    char_condition, _ = build_cross_rankings(_lines(), dictionaries=_dicts())
    by_label = {r.label: r for r in char_condition}
    assert by_label["Shohei Ohtani × PSA10"].revenue_usd == 864.0
    assert by_label["Luffy × Holo"].count == 1


def test_cross_character_price_band_top10() -> None:
    _, char_price = build_cross_rankings(_lines(), dictionaries=_dicts())
    by_label = {r.label: r for r in char_price}
    assert by_label["Luffy × $100-$300"].revenue_usd == 405.0
    assert by_label["Pikachu × <$100"].count == 1


def test_department_summary_uses_average_price_not_roi() -> None:
    rows = build_department_summary(_lines(), _profiles())
    by_dept = {r.department: r for r in rows}
    assert by_dept["Ohtani"].avg_price_usd == 864.0
    assert by_dept["One Piece"].count == 2
    assert by_dept["One Piece"].revenue_usd == 405.0


def test_monthly_trends_department_delta() -> None:
    current = build_department_summary(_lines()[:2], _profiles())
    previous = build_department_summary([SoldLine("p1", "p", "Luffy card", 100.0, "")], _profiles())
    trends = {r.label: r for r in build_monthly_trends(current, previous)}
    assert trends["Ohtani"].delta_usd == 864.0
    assert trends["One Piece"].delta_usd == 174.0


def test_empty_data_handling() -> None:
    report = build_intelligence_report([], _profiles(), month_label="2026年4月", dictionaries=_dicts())
    assert report.rankings["character"] == []
    assert report.cross_character_condition == []
    assert report.department_summary == []
    body = format_intelligence_markdown(report)
    assert "該当データなし" in body
    assert "| (データなし) | $0 | 0 |" in body


def test_report_with_previous_month_contains_trends() -> None:
    report = build_intelligence_report(
        _lines()[:1],
        _profiles(),
        month_label="2026年4月",
        previous_sold_lines=[SoldLine("p1", "p", "Shohei Ohtani PSA10", 500.0, "")],
        dictionaries=_dicts(),
    )
    assert report.department_trends
    body = format_intelligence_markdown(report)
    assert "## 前月比" in body
    assert "| Ohtani | $864 | $500 | $364 |" in body
    assert "## タグ別前月比" in body
    assert "| Shohei Ohtani | $864 | $500 | $364 |" in body


def test_build_tag_rankings_top_n_none_returns_all() -> None:
    rankings = build_tag_rankings(_lines(), dictionaries=_dicts(), top_n=None)
    assert len(rankings["character"]) == 3


def test_month_label_from_date() -> None:
    assert month_label_from_date(datetime(2026, 4, 1)) == "2026年4月"
