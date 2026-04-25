"""Capital Allocation 層: 部署別の予算配分推奨を生成する。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from common_rules import EXCHANGE_RATE_JPY_PER_USD
from reports.intelligence import DepartmentSummaryRow, TagRankingRow
from reports.market_signals import MarketSignalsReport

ENTRY_REVENUE_JPY = 50_000
EXPAND_REVENUE_JPY = 100_000
EXPAND_COUNT = 30
EXPAND_REQUIRED_MONTHS = 2
EXIT_REVENUE_JPY = 20_000
EXIT_REQUIRED_MONTHS = 3


@dataclass(frozen=True)
class DepartmentMonthSnapshot:
    month: str
    revenue_jpy: int
    count: int


@dataclass(frozen=True)
class AllocationRecommendation:
    department: str
    revenue_usd: float
    revenue_jpy: int
    count: int
    avg_price_usd: float
    allocation_pct: int
    action: str
    reason: str


@dataclass(frozen=True)
class AllocationReport:
    month_label: str
    recommendations: list[AllocationRecommendation]
    notes: list[str]


def revenue_jpy(revenue_usd: float, exchange_rate: float = EXCHANGE_RATE_JPY_PER_USD) -> int:
    return int(round(float(revenue_usd) * exchange_rate))


def _recent(history: Iterable[DepartmentMonthSnapshot], months: int) -> list[DepartmentMonthSnapshot]:
    return sorted(history, key=lambda x: x.month, reverse=True)[:months]


def decide_action(
    row: DepartmentSummaryRow,
    *,
    history: list[DepartmentMonthSnapshot] | None = None,
    exchange_rate: float = EXCHANGE_RATE_JPY_PER_USD,
) -> tuple[str, str]:
    hist = history or []
    recent_exit = _recent(hist, EXIT_REQUIRED_MONTHS)
    if len(recent_exit) >= EXIT_REQUIRED_MONTHS and all(x.revenue_jpy < EXIT_REVENUE_JPY for x in recent_exit):
        return ("撤退候補", "3ヶ月連続で月間売上 ¥20K 未満")

    recent_expand = _recent(hist, EXPAND_REQUIRED_MONTHS)
    if len(recent_expand) >= EXPAND_REQUIRED_MONTHS and all(
        x.revenue_jpy >= EXPAND_REVENUE_JPY and x.count >= EXPAND_COUNT for x in recent_expand
    ):
        return ("増額", "月間 ¥100K 以上かつ30件以上が2ヶ月連続")

    current_jpy = revenue_jpy(row.revenue_usd, exchange_rate)
    if current_jpy >= ENTRY_REVENUE_JPY:
        suffix = "(高単価)" if row.avg_price_usd >= 300 else ""
        return (f"拡大候補{suffix}", "月間 ¥50K 以上")

    if not hist and row.count < 5:
        return ("データ不足", "1ヶ月分のみ・件数不足")

    if current_jpy < EXIT_REVENUE_JPY:
        return ("縮小", "当月売上が ¥20K 未満")

    return ("維持", "売上は立っているが拡大基準未達")


def allocate_percentages(rows: list[DepartmentSummaryRow]) -> dict[str, int]:
    if not rows:
        return {}
    total = sum(max(0.0, r.revenue_usd) for r in rows)
    if total <= 0:
        base = 100 // len(rows)
        rem = 100 - base * len(rows)
        return {r.department: base + (1 if i < rem else 0) for i, r in enumerate(rows)}

    raw = [(r.department, max(0.0, r.revenue_usd) / total * 100.0) for r in rows]
    floored = {name: int(pct) for name, pct in raw}
    remainder = 100 - sum(floored.values())
    ranked = sorted(raw, key=lambda x: (-(x[1] - int(x[1])), x[0]))
    for name, _ in ranked[:remainder]:
        floored[name] += 1
    return floored


def build_market_notes(market: MarketSignalsReport | None) -> list[str]:
    if market is None:
        return ["Market Signals: データ不足"]
    notes: list[str] = []
    ex = market.exchange_rate
    if ex.current_rate is None or ex.deviation_pct is None:
        notes.append("為替: データ不足")
    else:
        level = "警告" if ex.warning else "警告レベル未満"
        notes.append(f"為替が設定値と {ex.deviation_pct:+.1f}% 乖離({level})")
    trend = market.trend
    if trend.change_pct is None:
        notes.append("当月件数の過去比: データ不足")
    else:
        notes.append(f"当月件数の過去比: {trend.change_pct:+.1f}%({trend.judgement})")
    return notes


def build_allocation_report(
    department_rows: list[DepartmentSummaryRow],
    *,
    tag_rankings: dict[str, list[TagRankingRow]] | None = None,
    market: MarketSignalsReport | None = None,
    history_by_department: dict[str, list[DepartmentMonthSnapshot]] | None = None,
    month_label: str,
    exchange_rate: float = EXCHANGE_RATE_JPY_PER_USD,
) -> AllocationReport:
    allocations = allocate_percentages(department_rows)
    history_by_department = history_by_department or {}
    recommendations: list[AllocationRecommendation] = []
    for row in sorted(department_rows, key=lambda r: (-r.revenue_usd, r.department)):
        action, reason = decide_action(
            row,
            history=history_by_department.get(row.department),
            exchange_rate=exchange_rate,
        )
        recommendations.append(
            AllocationRecommendation(
                department=row.department,
                revenue_usd=row.revenue_usd,
                revenue_jpy=revenue_jpy(row.revenue_usd, exchange_rate),
                count=row.count,
                avg_price_usd=row.avg_price_usd,
                allocation_pct=allocations.get(row.department, 0),
                action=action,
                reason=reason,
            )
        )

    notes = build_market_notes(market)
    if tag_rankings:
        top_chars = tag_rankings.get("character") or []
        if top_chars:
            notes.append(f"上位キャラタグ: {top_chars[0].tag} (${top_chars[0].revenue_usd:,.0f}/{top_chars[0].count}件)")
    return AllocationReport(month_label=month_label, recommendations=recommendations, notes=notes)


def format_allocation_markdown(report: AllocationReport) -> str:
    lines = [
        f"# {report.month_label} Capital Allocation レポート",
        "",
        "## 部署別推奨",
        "",
        "| 部署 | 当月売上 | 件数 | 推奨配分 | 推奨アクション | 理由 |",
        "|---|---:|---:|---:|---|---|",
    ]
    if not report.recommendations:
        lines.append("| (データなし) | ¥0 | 0 | 0% | データ不足 | 売上データなし |")
    for r in report.recommendations:
        lines.append(
            f"| {r.department} | ¥{r.revenue_jpy:,} | {r.count} | {r.allocation_pct}% | {r.action} | {r.reason} |"
        )
    lines.extend(["", "## 全体注意事項", ""])
    for note in report.notes:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"
