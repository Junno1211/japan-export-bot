"""
部署別売上レポートの集計と Markdown / ターミナル整形。

仕入れ価格が全 Sold 行で揃わない場合は利益列を None（=「不明」）とする。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from common_rules import EXCHANGE_RATE_JPY_PER_USD, calculate_profit_usd

from reports.department_classifier import DepartmentProfile, classify_title
from reports.ebay_data_fetcher import SoldLine
from reports.product_tagger import load_tag_dictionaries, tag_product


@dataclass(frozen=True)
class DepartmentSalesAgg:
    display_name: str
    revenue_usd: float
    count: int
    avg_profit_jpy: int | None
    total_profit_jpy: int | None

    @property
    def revenue_jpy(self) -> int:
        return int(round(self.revenue_usd * EXCHANGE_RATE_JPY_PER_USD))


@dataclass(frozen=True)
class TagSalesAgg:
    tag: str
    revenue_usd: float
    count: int


TAG_SECTION_TITLES = {
    "character": "キャラ別",
    "condition": "状態別",
    "series": "シリーズ別",
    "price_band": "価格帯別",
}

PRICE_BAND_LABELS = {
    "low": "<$100",
    "mid": "$100-$300",
    "high": "$300-$1000",
    "premium": "$1000+",
}


def month_range_tokyo(now: datetime | None = None) -> tuple[datetime, datetime]:
    """当月 1 日 00:00 (Asia/Tokyo) 〜 指定時刻（既定: 実行時点）。"""
    tz = ZoneInfo("Asia/Tokyo")
    n = now or datetime.now(tz)
    if n.tzinfo is None:
        n = n.replace(tzinfo=tz)
    else:
        n = n.astimezone(tz)
    start = n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, n


def _profits_enabled(sold_lines: list[SoldLine], item_cost_jpy: dict[str, int]) -> bool:
    if not sold_lines:
        return False
    for ln in sold_lines:
        if not ln.item_id:
            return False
        if ln.item_id not in item_cost_jpy:
            return False
    return True


def _profit_jpy_for_line(price_usd: float, cost_jpy: int) -> int:
    p_usd = calculate_profit_usd(price_usd, float(cost_jpy))
    return int(round(p_usd * EXCHANGE_RATE_JPY_PER_USD))


def aggregate_sales_by_department(
    sold_lines: list[SoldLine],
    profiles: list[DepartmentProfile],
    item_cost_jpy: dict[str, int],
) -> tuple[list[DepartmentSalesAgg], dict[str, Any]]:
    """
    部署別に売上・件数を集計。利益は item_cost_jpy が全行分揃っているときのみ算出。
    """
    use_profit = _profits_enabled(sold_lines, item_cost_jpy)

    buckets: dict[str, dict[str, Any]] = {}
    unclassified = 0

    for ln in sold_lines:
        _, display = classify_title(ln.title, profiles)
        if display == "未分類":
            unclassified += 1
        b = buckets.setdefault(
            display,
            {"revenue_usd": 0.0, "count": 0, "profits": [] if use_profit else None},
        )
        b["revenue_usd"] += float(ln.price_usd)
        b["count"] += 1
        if use_profit and b["profits"] is not None:
            cost = item_cost_jpy[ln.item_id]
            b["profits"].append(_profit_jpy_for_line(float(ln.price_usd), int(cost)))

    rows: list[DepartmentSalesAgg] = []
    for name, data in buckets.items():
        avg_p: int | None
        tot_p: int | None
        if use_profit and data["profits"] is not None:
            plist: list[int] = data["profits"]
            tot_p = sum(plist)
            avg_p = int(round(tot_p / len(plist))) if plist else None
        else:
            avg_p = None
            tot_p = None
        rows.append(
            DepartmentSalesAgg(
                display_name=name,
                revenue_usd=data["revenue_usd"],
                count=int(data["count"]),
                avg_profit_jpy=avg_p,
                total_profit_jpy=tot_p,
            )
        )

    def _sort_key(r: DepartmentSalesAgg) -> tuple[int, str]:
        return (1 if r.display_name == "未分類" else 0, r.display_name)

    rows.sort(key=_sort_key)

    meta = {
        "unclassified_count": unclassified,
        "profits_enabled": use_profit,
    }
    return rows, meta


def _tag_sort_key(row: TagSalesAgg) -> tuple[int, float, str]:
    return (1 if row.tag == "(該当なし)" else 0, -row.revenue_usd, row.tag)


def _canonical_tags_for_aggregation(tags: list[str]) -> list[str]:
    """包含関係のあるタグは長い（より具体的な）タグだけを集計代表にする。"""
    kept: list[str] = []
    for tag in sorted(tags, key=lambda x: (-len(x), x.casefold())):
        low = tag.casefold()
        if any(low in k.casefold() or k.casefold() in low for k in kept):
            continue
        kept.append(tag)
    return sorted(kept, key=lambda x: tags.index(x))


def aggregate_sales_by_tags(
    sold_lines: list[SoldLine],
    *,
    dictionaries: dict[str, Any] | None = None,
) -> dict[str, list[TagSalesAgg]]:
    """商品タグ別に売上・件数を集計する。部署別集計とは独立した横断集計。"""
    dictionaries = dictionaries if dictionaries is not None else load_tag_dictionaries()
    buckets: dict[str, dict[str, dict[str, float | int]]] = {
        "character": {},
        "condition": {},
        "series": {},
        "price_band": {},
    }

    for ln in sold_lines:
        price = float(ln.price_usd)
        tags = tag_product(ln.title, price, dictionaries=dictionaries)
        for category in ("character", "condition", "series"):
            names = _canonical_tags_for_aggregation(tags.get(category) or []) or ["(該当なし)"]
            for name in names:
                b = buckets[category].setdefault(name, {"revenue_usd": 0.0, "count": 0})
                b["revenue_usd"] = float(b["revenue_usd"]) + price
                b["count"] = int(b["count"]) + 1

        price_names = tags.get("price_band") or ["(該当なし)"]
        for name in price_names:
            label = PRICE_BAND_LABELS.get(name, name)
            b = buckets["price_band"].setdefault(label, {"revenue_usd": 0.0, "count": 0})
            b["revenue_usd"] = float(b["revenue_usd"]) + price
            b["count"] = int(b["count"]) + 1

    for label in PRICE_BAND_LABELS.values():
        buckets["price_band"].setdefault(label, {"revenue_usd": 0.0, "count": 0})

    sections: dict[str, list[TagSalesAgg]] = {}
    for category, data in buckets.items():
        rows = [
            TagSalesAgg(tag=name, revenue_usd=float(v["revenue_usd"]), count=int(v["count"]))
            for name, v in data.items()
        ]
        if category == "price_band":
            order = {label: i for i, label in enumerate(PRICE_BAND_LABELS.values())}
            rows.sort(key=lambda r: (order.get(r.tag, 999), r.tag))
        else:
            rows.sort(key=_tag_sort_key)
        sections[category] = rows
    return sections


def format_profit_cell(v: int | None) -> str:
    if v is None:
        return "不明"
    return f"{v:,}"


def format_terminal_table(
    year: int,
    month: int,
    day_start: int,
    day_end: int,
    rows: list[DepartmentSalesAgg],
    *,
    total_row: DepartmentSalesAgg,
    tag_sections: dict[str, list[TagSalesAgg]] | None = None,
) -> str:
    title = f"{year}年{month}月 部署別売上レポート ({day_start}日〜{day_end}日)"
    sep = "─" * 73
    header = (
        f"{'部署':<14} | {'売上(USD)':>10} | {'売上(JPY)':>12} | {'件数':>5} | "
        f"{'平均利益(JPY)':>14} | {'合計利益(JPY)':>14}"
    )
    lines_out = [title, "", header, sep]
    for r in rows:
        lines_out.append(
            f"{r.display_name:<14} | {r.revenue_usd:>10,.0f} | {r.revenue_jpy:>12,} | {r.count:>5} | "
            f"{format_profit_cell(r.avg_profit_jpy):>14} | {format_profit_cell(r.total_profit_jpy):>14}"
        )
    lines_out.append(sep)
    lines_out.append(
        f"{'合計':<14} | {total_row.revenue_usd:>10,.0f} | {total_row.revenue_jpy:>12,} | {total_row.count:>5} | "
        f"{format_profit_cell(total_row.avg_profit_jpy):>14} | {format_profit_cell(total_row.total_profit_jpy):>14}"
    )
    lines_out.append("")
    lines_out.append(
        f"参考: 為替レート {int(EXCHANGE_RATE_JPY_PER_USD)} JPY/USD、手数料率 19.6%、最低利益基準 ¥3,000"
    )
    if tag_sections:
        for category in ("character", "condition", "series", "price_band"):
            tag_rows = tag_sections.get(category) or []
            width = max([14, *[len(r.tag) for r in tag_rows]])
            lines_out.extend(
                [
                    "",
                    f"## {TAG_SECTION_TITLES[category]}",
                    f"{'タグ':<{width}} | {'売上(USD)':>9} | {'件数':>4}",
                    "─" * (width + 20),
                ]
            )
            for r in tag_rows:
                lines_out.append(f"{r.tag:<{width}} | {r.revenue_usd:>9,.0f} | {r.count:>4}")
    return "\n".join(lines_out)


def build_total_row(rows: list[DepartmentSalesAgg]) -> DepartmentSalesAgg:
    ru = sum(r.revenue_usd for r in rows)
    c = sum(r.count for r in rows)
    any_unknown = any(r.avg_profit_jpy is None for r in rows)
    if any_unknown or c == 0:
        return DepartmentSalesAgg(
            display_name="合計",
            revenue_usd=ru,
            count=c,
            avg_profit_jpy=None,
            total_profit_jpy=None,
        )
    tp = sum(int(r.total_profit_jpy or 0) for r in rows)
    ap = int(round(tp / c)) if c else None
    return DepartmentSalesAgg(
        display_name="合計",
        revenue_usd=ru,
        count=c,
        avg_profit_jpy=ap,
        total_profit_jpy=tp,
    )


def write_markdown_report(
    path: Path,
    year: int,
    month: int,
    date_from: str,
    date_to: str,
    rows: list[DepartmentSalesAgg],
    total_row: DepartmentSalesAgg,
    *,
    unclassified_count: int,
    profits_enabled: bool,
    tag_sections: dict[str, list[TagSalesAgg]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        f"# {year}年{month}月 部署別売上レポート",
        "",
        f"集計期間: {date_from} ~ {date_to}",
        "",
        "| 部署 | 売上(USD) | 売上(JPY) | 件数 | 平均利益(JPY) | 合計利益(JPY) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            "| {name} | {usd:,.0f} | {jpy:,} | {cnt} | {avg} | {tot} |".format(
                name=r.display_name,
                usd=r.revenue_usd,
                jpy=r.revenue_jpy,
                cnt=r.count,
                avg=format_profit_cell(r.avg_profit_jpy),
                tot=format_profit_cell(r.total_profit_jpy),
            )
        )
    lines.append(
        "| **合計** | **{usd:,.0f}** | **{jpy:,}** | **{cnt}** | **{avg}** | **{tot}** |".format(
            usd=total_row.revenue_usd,
            jpy=total_row.revenue_jpy,
            cnt=total_row.count,
            avg=format_profit_cell(total_row.avg_profit_jpy),
            tot=format_profit_cell(total_row.total_profit_jpy),
        )
    )
    if tag_sections:
        for category in ("character", "condition", "series", "price_band"):
            tag_rows = tag_sections.get(category) or []
            lines.extend(
                [
                    "",
                    f"## {TAG_SECTION_TITLES[category]}",
                    "",
                    "| タグ | 売上(USD) | 件数 |",
                    "|---|---:|---:|",
                ]
            )
            for tr in tag_rows:
                lines.append(f"| {tr.tag} | {tr.revenue_usd:,.0f} | {tr.count} |")
    lines.extend(
        [
            "",
            "## 参考情報",
            "",
            f"- 為替レート: {int(EXCHANGE_RATE_JPY_PER_USD)} JPY/USD",
            "- 総手数料率: 19.6%",
            "- 最低利益基準: ¥3,000",
            "",
            "## 部署判定について",
            "",
            "- 判定方式: タイトル + キーワード辞書",
            "- 辞書ソース: `sourcing/<部署>/keywords.json`",
            f"- 未分類件数: {unclassified_count} 件（タイトルから部署を特定できなかった商品）",
            f"- 利益列: {'common_rules.calculate_profit_usd に基づき算出' if profits_enabled else '仕入れ価格が取得できないため「不明」'}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def try_load_item_cost_jpy(project_root: Path) -> dict[str, int]:
    """
    将来用: item_id → 仕入れ(円)。現状 items.csv に価格列がないため常に空 dict を返す。
    """
    return {}
