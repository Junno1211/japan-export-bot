"""為替・季節・販売件数トレンドの Market Signal 分析。"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common_rules import EXCHANGE_RATE_JPY_PER_USD

logger = logging.getLogger(__name__)

FRANKFURTER_LATEST_URL = "https://api.frankfurter.app/latest?from=USD&to=JPY"
FRANKFURTER_SERIES_URL = "https://api.frankfurter.app/{start}..{end}?from=USD&to=JPY"
EXCHANGE_WARNING_THRESHOLD_PCT = 5.0
TREND_WARNING_THRESHOLD_PCT = 30.0


@dataclass(frozen=True)
class ExchangeRateSignal:
    current_rate: float | None
    configured_rate: float
    deviation_pct: float | None
    warning: bool
    history_30d: list[tuple[str, float]]
    error: str | None = None


@dataclass(frozen=True)
class SeasonalitySignal:
    month: int
    status: str
    message: str
    same_month_average_count: float | None = None
    annual_average_count: float | None = None
    relative_to_annual_pct: float | None = None


@dataclass(frozen=True)
class TrendSignal:
    current_count: int | None
    previous_3mo_average: float | None
    change_pct: float | None
    judgement: str


@dataclass(frozen=True)
class MarketSignalsReport:
    report_date: str
    exchange_rate: ExchangeRateSignal
    seasonality: SeasonalitySignal
    trend: TrendSignal


JsonFetcher = Callable[[str], dict[str, Any]]


def fetch_json(url: str, *, timeout: float = 10.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(str(e)) from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSON parse error: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError("API response is not an object")
    return data


def calculate_deviation_pct(current_rate: float, configured_rate: float = EXCHANGE_RATE_JPY_PER_USD) -> float:
    if configured_rate == 0:
        return 0.0
    return (float(current_rate) - float(configured_rate)) / float(configured_rate) * 100.0


def calculate_pct_change(current_value: float, baseline_value: float) -> float:
    if baseline_value == 0:
        return 0.0
    return (float(current_value) - float(baseline_value)) / float(baseline_value) * 100.0


def parse_latest_usd_jpy(data: dict[str, Any]) -> float:
    rates = data.get("rates")
    if not isinstance(rates, dict) or "JPY" not in rates:
        raise RuntimeError("JPY rate missing")
    return float(rates["JPY"])


def parse_series_usd_jpy(data: dict[str, Any]) -> list[tuple[str, float]]:
    rates = data.get("rates")
    if not isinstance(rates, dict):
        raise RuntimeError("rates missing")
    out: list[tuple[str, float]] = []
    for day in sorted(rates):
        row = rates[day]
        if isinstance(row, dict) and "JPY" in row:
            out.append((str(day), float(row["JPY"])))
    return out


def build_exchange_rate_signal(
    *,
    today: date,
    configured_rate: float = EXCHANGE_RATE_JPY_PER_USD,
    fetcher: JsonFetcher = fetch_json,
) -> ExchangeRateSignal:
    try:
        latest = fetcher(FRANKFURTER_LATEST_URL)
        current = parse_latest_usd_jpy(latest)
    except Exception as e:  # noqa: BLE001 - レポート生成を止めないため広く握る
        logger.warning("為替 API 取得に失敗: %s", e)
        return ExchangeRateSignal(
            current_rate=None,
            configured_rate=float(configured_rate),
            deviation_pct=None,
            warning=False,
            history_30d=[],
            error=str(e),
        )

    history: list[tuple[str, float]] = []
    history_error: str | None = None
    try:
        start = today - timedelta(days=30)
        series_url = FRANKFURTER_SERIES_URL.format(start=start.isoformat(), end=today.isoformat())
        history = parse_series_usd_jpy(fetcher(series_url))
    except Exception as e:  # noqa: BLE001 - 30日履歴なしでも現在値は有効
        history_error = f"30日履歴取得失敗: {e}"
        logger.warning(history_error)

    deviation = calculate_deviation_pct(current, configured_rate)
    return ExchangeRateSignal(
        current_rate=current,
        configured_rate=float(configured_rate),
        deviation_pct=deviation,
        warning=abs(deviation) >= EXCHANGE_WARNING_THRESHOLD_PCT,
        history_30d=history,
        error=history_error,
    )


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def previous_month_keys(target: date, months: int) -> list[str]:
    keys: list[str] = []
    y, m = target.year, target.month
    for _ in range(months):
        m -= 1
        if m == 0:
            y -= 1
            m = 12
        keys.append(f"{y:04d}-{m:02d}")
    return keys


def build_seasonality_signal(target: date, monthly_counts: dict[str, int] | None = None) -> SeasonalitySignal:
    counts = monthly_counts or {}
    same_month = [
        count
        for key, count in counts.items()
        if len(key) == 7 and key.endswith(f"-{target.month:02d}") and not key.startswith(f"{target.year:04d}-")
    ]
    if not counts or not same_month:
        return SeasonalitySignal(
            month=target.month,
            status="データ不足",
            message=f"{target.month}月の過去同月データが不足しています",
        )

    same_avg = sum(same_month) / len(same_month)
    target_key = month_key(target)
    complete_counts = {k: v for k, v in counts.items() if k != target_key}
    annual_avg = sum(complete_counts.values()) / len(complete_counts) if complete_counts else 0.0
    rel = calculate_pct_change(same_avg, annual_avg) if annual_avg else 0.0
    if rel >= 10.0:
        status = "ハイシーズン"
    elif rel <= -10.0:
        status = "ローシーズン"
    else:
        status = "通常"
    return SeasonalitySignal(
        month=target.month,
        status=status,
        message=f"{target.month}月は年間平均比 {rel:+.1f}%",
        same_month_average_count=same_avg,
        annual_average_count=annual_avg,
        relative_to_annual_pct=rel,
    )


def build_trend_signal(target: date, monthly_counts: dict[str, int] | None = None) -> TrendSignal:
    counts = monthly_counts or {}
    current = counts.get(month_key(target))
    prev_keys = previous_month_keys(target, 3)
    prev_values = [counts[k] for k in prev_keys if k in counts]
    if current is None or len(prev_values) < 3:
        return TrendSignal(
            current_count=current,
            previous_3mo_average=None,
            change_pct=None,
            judgement="データ不足",
        )

    avg = sum(prev_values) / 3
    change = calculate_pct_change(current, avg) if avg else 0.0
    if change >= TREND_WARNING_THRESHOLD_PCT:
        judgement = "急増"
    elif change <= -TREND_WARNING_THRESHOLD_PCT:
        judgement = "急減"
    else:
        judgement = "通常"
    return TrendSignal(
        current_count=current,
        previous_3mo_average=avg,
        change_pct=change,
        judgement=judgement,
    )


def build_market_signals(
    *,
    today: date,
    monthly_counts: dict[str, int] | None = None,
    fetcher: JsonFetcher = fetch_json,
) -> MarketSignalsReport:
    return MarketSignalsReport(
        report_date=today.isoformat(),
        exchange_rate=build_exchange_rate_signal(today=today, fetcher=fetcher),
        seasonality=build_seasonality_signal(today, monthly_counts),
        trend=build_trend_signal(today, monthly_counts),
    )


def report_to_dict(report: MarketSignalsReport) -> dict[str, Any]:
    return asdict(report)


def format_market_signals_markdown(report: MarketSignalsReport) -> str:
    ex = report.exchange_rate
    if ex.current_rate is None:
        exchange_lines = [
            "- 現在: データ不足",
            f"- 設定値: {ex.configured_rate:.1f} JPY/USD",
            f"- 取得エラー: {ex.error or '不明'}",
        ]
    else:
        level = "警告" if ex.warning else "警告レベル未満"
        exchange_lines = [
            f"- 現在: {ex.current_rate:.1f} JPY/USD",
            f"- 設定値: {ex.configured_rate:.1f} JPY/USD",
            f"- 乖離: {ex.deviation_pct:+.1f}%({level})",
            f"- 過去30日データ点数: {len(ex.history_30d)}",
        ]

    season = report.seasonality
    trend = report.trend
    trend_avg = "不明(データ不足)" if trend.previous_3mo_average is None else f"{trend.previous_3mo_average:.1f}件"
    trend_count = "不明" if trend.current_count is None else f"{trend.current_count}件"

    lines = [
        f"# Market Signals - {report.report_date}",
        "",
        "## 為替レート(JPY/USD)",
        *exchange_lines,
        "",
        "## 季節要因",
        f"- {season.message}",
        f"- 判定: {season.status}",
        "",
        "## トレンド検出",
        f"- 当月件数: {trend_count}",
        f"- 過去3ヶ月平均: {trend_avg}",
        f"- 判定: {trend.judgement}",
    ]
    if trend.change_pct is not None:
        lines.append(f"- 増減率: {trend.change_pct:+.1f}%")
    return "\n".join(lines) + "\n"
