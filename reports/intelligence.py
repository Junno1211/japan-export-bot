"""売上データから売れ筋パターンを抽出する Intelligence 層。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from reports.department_classifier import DepartmentProfile, classify_title
from reports.ebay_data_fetcher import SoldLine
from reports.product_tagger import load_tag_dictionaries, tag_product
from reports.report_generator import PRICE_BAND_LABELS

TAG_CATEGORY_LABELS = {
    "character": "キャラ別",
    "condition": "状態別",
    "series": "シリーズ別",
    "price_band": "価格帯別",
}


@dataclass(frozen=True)
class TagRankingRow:
    category: str
    tag: str
    revenue_usd: float
    count: int


@dataclass(frozen=True)
class CrossRankingRow:
    label: str
    left_tag: str
    right_tag: str
    revenue_usd: float
    count: int


@dataclass(frozen=True)
class DepartmentSummaryRow:
    department: str
    count: int
    avg_price_usd: float
    revenue_usd: float


@dataclass(frozen=True)
class TrendRow:
    label: str
    current_usd: float
    previous_usd: float

    @property
    def delta_usd(self) -> float:
        return self.current_usd - self.previous_usd


@dataclass(frozen=True)
class IntelligenceReport:
    month_label: str
    rankings: dict[str, list[TagRankingRow]]
    cross_character_condition: list[CrossRankingRow]
    cross_character_price_band: list[CrossRankingRow]
    department_summary: list[DepartmentSummaryRow]
    department_trends: list[TrendRow]
    tag_trends: dict[str, list[TrendRow]]


def _sort_revenue_count(name: str, revenue: float, count: int) -> tuple[float, int, str]:
    return (-revenue, -count, name)


def _tag_rows_for_line(
    line: SoldLine,
    dictionaries: dict[str, Any],
) -> dict[str, list[str]]:
    tags = tag_product(line.title, float(line.price_usd), dictionaries=dictionaries)
    out: dict[str, list[str]] = {}
    for category in ("character", "condition", "series"):
        out[category] = _canonical_tags(tags.get(category) or []) or ["(該当なし)"]
    out["price_band"] = [PRICE_BAND_LABELS.get(x, x) for x in (tags.get("price_band") or ["(該当なし)"])]
    return out


def _canonical_tags(tags: list[str]) -> list[str]:
    kept: list[str] = []
    for tag in sorted(tags, key=lambda x: (-len(x), x.casefold())):
        low = tag.casefold()
        if any(low in k.casefold() or k.casefold() in low for k in kept):
            continue
        kept.append(tag)
    return sorted(kept, key=lambda x: tags.index(x))


def build_tag_rankings(
    sold_lines: list[SoldLine],
    *,
    dictionaries: dict[str, Any] | None = None,
    top_n: int | None = 5,
) -> dict[str, list[TagRankingRow]]:
    dictionaries = dictionaries if dictionaries is not None else load_tag_dictionaries()
    buckets: dict[str, dict[str, dict[str, float | int]]] = {
        "character": {},
        "condition": {},
        "series": {},
        "price_band": {},
    }
    for line in sold_lines:
        price = float(line.price_usd)
        tags = _tag_rows_for_line(line, dictionaries)
        for category, names in tags.items():
            for name in names:
                b = buckets[category].setdefault(name, {"revenue_usd": 0.0, "count": 0})
                b["revenue_usd"] = float(b["revenue_usd"]) + price
                b["count"] = int(b["count"]) + 1

    rankings: dict[str, list[TagRankingRow]] = {}
    for category, data in buckets.items():
        rows = [
            TagRankingRow(category, tag, float(v["revenue_usd"]), int(v["count"]))
            for tag, v in data.items()
            if tag != "(該当なし)"
        ]
        rows.sort(key=lambda r: _sort_revenue_count(r.tag, r.revenue_usd, r.count))
        rankings[category] = rows if top_n is None else rows[:top_n]
    return rankings


def build_cross_rankings(
    sold_lines: list[SoldLine],
    *,
    dictionaries: dict[str, Any] | None = None,
    top_n: int = 10,
) -> tuple[list[CrossRankingRow], list[CrossRankingRow]]:
    dictionaries = dictionaries if dictionaries is not None else load_tag_dictionaries()
    char_condition: dict[tuple[str, str], dict[str, float | int]] = {}
    char_price: dict[tuple[str, str], dict[str, float | int]] = {}

    for line in sold_lines:
        price = float(line.price_usd)
        tags = _tag_rows_for_line(line, dictionaries)
        characters = [x for x in tags["character"] if x != "(該当なし)"]
        conditions = [x for x in tags["condition"] if x != "(該当なし)"]
        price_bands = [x for x in tags["price_band"] if x != "(該当なし)"]

        for char in characters:
            for condition in conditions:
                b = char_condition.setdefault((char, condition), {"revenue_usd": 0.0, "count": 0})
                b["revenue_usd"] = float(b["revenue_usd"]) + price
                b["count"] = int(b["count"]) + 1
            for band in price_bands:
                b = char_price.setdefault((char, band), {"revenue_usd": 0.0, "count": 0})
                b["revenue_usd"] = float(b["revenue_usd"]) + price
                b["count"] = int(b["count"]) + 1

    def _rows(src: dict[tuple[str, str], dict[str, float | int]]) -> list[CrossRankingRow]:
        rows = [
            CrossRankingRow(
                label=f"{left} × {right}",
                left_tag=left,
                right_tag=right,
                revenue_usd=float(v["revenue_usd"]),
                count=int(v["count"]),
            )
            for (left, right), v in src.items()
        ]
        rows.sort(key=lambda r: _sort_revenue_count(r.label, r.revenue_usd, r.count))
        return rows[:top_n]

    return _rows(char_condition), _rows(char_price)


def build_department_summary(
    sold_lines: list[SoldLine],
    profiles: list[DepartmentProfile],
) -> list[DepartmentSummaryRow]:
    buckets: dict[str, dict[str, float | int]] = {}
    for line in sold_lines:
        _, display = classify_title(line.title, profiles)
        price = float(line.price_usd)
        b = buckets.setdefault(display, {"revenue_usd": 0.0, "count": 0})
        b["revenue_usd"] = float(b["revenue_usd"]) + price
        b["count"] = int(b["count"]) + 1

    rows = []
    for dept, data in buckets.items():
        count = int(data["count"])
        revenue = float(data["revenue_usd"])
        rows.append(
            DepartmentSummaryRow(
                department=dept,
                count=count,
                avg_price_usd=(revenue / count) if count else 0.0,
                revenue_usd=revenue,
            )
        )
    rows.sort(key=lambda r: _sort_revenue_count(r.department, r.revenue_usd, r.count))
    return rows


def build_monthly_trends(
    current_rows: list[DepartmentSummaryRow],
    previous_rows: list[DepartmentSummaryRow],
) -> list[TrendRow]:
    current = {r.department: r.revenue_usd for r in current_rows}
    previous = {r.department: r.revenue_usd for r in previous_rows}
    labels = sorted(set(current) | set(previous))
    rows = [TrendRow(label, current.get(label, 0.0), previous.get(label, 0.0)) for label in labels]
    rows.sort(key=lambda r: (-abs(r.delta_usd), r.label))
    return rows


def build_tag_trends(
    current: dict[str, list[TagRankingRow]],
    previous: dict[str, list[TagRankingRow]],
) -> dict[str, list[TrendRow]]:
    out: dict[str, list[TrendRow]] = {}
    for category in ("character", "condition", "series", "price_band"):
        cur = {r.tag: r.revenue_usd for r in current.get(category, [])}
        prev = {r.tag: r.revenue_usd for r in previous.get(category, [])}
        labels = sorted(set(cur) | set(prev))
        rows = [TrendRow(label, cur.get(label, 0.0), prev.get(label, 0.0)) for label in labels]
        rows.sort(key=lambda r: (-abs(r.delta_usd), r.label))
        out[category] = rows[:10]
    return out


def build_intelligence_report(
    sold_lines: list[SoldLine],
    profiles: list[DepartmentProfile],
    *,
    month_label: str,
    previous_sold_lines: list[SoldLine] | None = None,
    dictionaries: dict[str, Any] | None = None,
) -> IntelligenceReport:
    full_rankings = build_tag_rankings(sold_lines, dictionaries=dictionaries, top_n=None)
    rankings = {category: rows[:5] for category, rows in full_rankings.items()}
    cross_condition, cross_price_band = build_cross_rankings(sold_lines, dictionaries=dictionaries)
    department_summary = build_department_summary(sold_lines, profiles)

    department_trends: list[TrendRow] = []
    tag_trends: dict[str, list[TrendRow]] = {}
    if previous_sold_lines is not None:
        prev_summary = build_department_summary(previous_sold_lines, profiles)
        department_trends = build_monthly_trends(department_summary, prev_summary)
        prev_rankings = build_tag_rankings(previous_sold_lines, dictionaries=dictionaries, top_n=None)
        tag_trends = build_tag_trends(full_rankings, prev_rankings)

    return IntelligenceReport(
        month_label=month_label,
        rankings=rankings,
        cross_character_condition=cross_condition,
        cross_character_price_band=cross_price_band,
        department_summary=department_summary,
        department_trends=department_trends,
        tag_trends=tag_trends,
    )


def _usd(v: float) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.0f}"


def format_intelligence_markdown(report: IntelligenceReport) -> str:
    lines = [f"# {report.month_label} Intelligence レポート", "", "## 売上ランキング Top 5", ""]
    for category in ("character", "condition", "series", "price_band"):
        lines.extend([f"### {TAG_CATEGORY_LABELS[category]}", ""])
        rows = report.rankings.get(category) or []
        if not rows:
            lines.extend(["該当データなし", ""])
            continue
        for i, row in enumerate(rows, start=1):
            lines.append(f"{i}. {row.tag} — {_usd(row.revenue_usd)} / {row.count}件")
        lines.append("")

    lines.extend(["## クロス集計 Top 10", "", "### キャラ × 状態", ""])
    lines.extend(_cross_table(report.cross_character_condition, "キャラ × 状態"))
    lines.extend(["", "### キャラ × 価格帯", ""])
    lines.extend(_cross_table(report.cross_character_price_band, "キャラ × 価格帯"))

    lines.extend(["", "## 部署別サマリー", "", "| 部署 | 件数 | 平均販売価格 | 売上 |", "|---|---:|---:|---:|"])
    for row in report.department_summary:
        lines.append(f"| {row.department} | {row.count} | {_usd(row.avg_price_usd)} | {_usd(row.revenue_usd)} |")
    if not report.department_summary:
        lines.append("| (データなし) | 0 | $0 | $0 |")

    if report.department_trends:
        lines.extend(["", "## 前月比", "", "| 部署 | 当月 | 前月 | 増減 |", "|---|---:|---:|---:|"])
        for row in report.department_trends:
            lines.append(f"| {row.label} | {_usd(row.current_usd)} | {_usd(row.previous_usd)} | {_usd(row.delta_usd)} |")

    if report.tag_trends:
        lines.extend(["", "## タグ別前月比", ""])
        for category in ("character", "condition", "series", "price_band"):
            rows = report.tag_trends.get(category) or []
            lines.extend(
                [
                    f"### {TAG_CATEGORY_LABELS[category]}",
                    "",
                    "| タグ | 当月 | 前月 | 増減 |",
                    "|---|---:|---:|---:|",
                ]
            )
            if not rows:
                lines.append("| (データなし) | $0 | $0 | $0 |")
            else:
                for row in rows:
                    lines.append(
                        f"| {row.label} | {_usd(row.current_usd)} | {_usd(row.previous_usd)} | {_usd(row.delta_usd)} |"
                    )
            lines.append("")

    return "\n".join(lines) + "\n"


def _cross_table(rows: list[CrossRankingRow], heading: str) -> list[str]:
    out = [f"| {heading} | 売上 | 件数 |", "|---|---:|---:|"]
    if not rows:
        out.append("| (データなし) | $0 | 0 |")
        return out
    for row in rows:
        out.append(f"| {row.label} | {_usd(row.revenue_usd)} | {row.count} |")
    return out


def month_label_from_date(start: datetime) -> str:
    return f"{start.year}年{start.month}月"
