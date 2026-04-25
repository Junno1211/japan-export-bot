"""generate_intelligence_report CLI 補助関数のテスト。"""

from __future__ import annotations

from datetime import timezone
from unittest.mock import patch

from reports.ebay_data_fetcher import SoldLine
from reports.generate_intelligence_report import main, parse_month_arg, previous_month_range


def test_parse_month_arg_specific_month() -> None:
    start, end = parse_month_arg("2026-04")
    assert (start.year, start.month, start.day) == (2026, 4, 1)
    assert (end.year, end.month, end.day) == (2026, 5, 1)


def test_parse_month_arg_december_rollover() -> None:
    start, end = parse_month_arg("2026-12")
    assert (start.year, start.month, start.day) == (2026, 12, 1)
    assert (end.year, end.month, end.day) == (2027, 1, 1)


def test_previous_month_range_january_rollover() -> None:
    start, _ = parse_month_arg("2026-01")
    prev_start, prev_end = previous_month_range(start)
    assert (prev_start.year, prev_start.month, prev_start.day) == (2025, 12, 1)
    assert prev_end == start
    assert prev_start.astimezone(timezone.utc) < prev_end.astimezone(timezone.utc)


def test_main_writes_markdown_without_live_api(tmp_path, capsys) -> None:
    with patch("reports.generate_intelligence_report.ROOT", tmp_path):
        with patch("reports.generate_intelligence_report.load_department_profiles", return_value=[]):
            with patch(
                "reports.generate_intelligence_report.fetch_completed_orders",
                return_value=[SoldLine("o1", "1", "Shohei Ohtani PSA10", 864.0, "")],
            ):
                main(["--month", "2026-04"])
    out = capsys.readouterr().out
    path = tmp_path / "reports" / "output" / "intelligence_2026-04.md"
    assert "レポート保存" in out
    assert path.exists()
    assert "2026年4月 Intelligence レポート" in path.read_text(encoding="utf-8")
