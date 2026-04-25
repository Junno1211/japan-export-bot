"""日次パイプラインのテスト。"""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from reports.run_daily_pipeline import (
    PipelineStepResult,
    build_slack_message,
    format_daily_report,
    load_slack_webhook_url,
    main,
    run_pipeline,
    run_step,
    save_daily_report,
    send_slack_message,
)


def _completed(code: int = 0, out: str = "ok", err: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["cmd"], code, out, err)


def test_run_step_success() -> None:
    result = run_step("X", "x.py", runner=lambda _cmd: _completed(0, "done", ""))
    assert result.ok is True
    assert result.stdout == "done"


def test_run_step_exception_becomes_failure() -> None:
    def bad(_cmd):
        raise RuntimeError("boom")

    result = run_step("X", "x.py", runner=bad)
    assert result.ok is False
    assert "boom" in result.stderr


def test_run_pipeline_continues_after_failure() -> None:
    calls = []

    def runner(cmd):
        calls.append(cmd)
        return _completed(1 if len(calls) == 2 else 0)

    results = run_pipeline(runner=runner)
    assert len(results) == 4
    assert [r.ok for r in results] == [True, False, True, True]


def test_format_daily_report_contains_success_and_failure() -> None:
    body = format_daily_report(
        [
            PipelineStepResult("A", ["python", "a.py"], 0, "ok", ""),
            PipelineStepResult("B", ["python", "b.py"], 1, "", "ng"),
        ],
        today=date(2026, 4, 25),
    )
    assert "# Daily Phase 1 Pipeline - 2026-04-25" in body
    assert "| A | 成功 | 0 |" in body
    assert "| B | 失敗 | 1 |" in body


def test_save_daily_report(tmp_path: Path) -> None:
    with patch("reports.run_daily_pipeline.ROOT", tmp_path):
        path = save_daily_report("body", today=date(2026, 4, 25))
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "body"


def test_load_slack_webhook_missing_config_returns_none() -> None:
    with patch.dict("sys.modules", {"config": None}):
        assert load_slack_webhook_url() is None


def test_build_slack_message_marks_failure() -> None:
    text = build_slack_message(
        [
            PipelineStepResult("A", ["a"], 0, "", ""),
            PipelineStepResult("B", ["b"], 1, "", ""),
        ],
        Path("daily.md"),
    )
    assert "成功 1 / 失敗 1" in text
    assert "B: 失敗しました" in text


def test_send_slack_message_posts_payload() -> None:
    response = MagicMock()
    response.status = 200
    response.__enter__.return_value = response
    response.__exit__.return_value = None
    with patch("reports.run_daily_pipeline.urllib.request.urlopen", return_value=response) as mock_open:
        assert send_slack_message("https://example.test/hook", "hello") is True
    req = mock_open.call_args.args[0]
    assert req.full_url == "https://example.test/hook"
    assert b"hello" in req.data


def test_main_no_slack_returns_failure_when_any_step_fails(tmp_path: Path, capsys) -> None:
    results = [
        PipelineStepResult("A", ["a"], 0, "ok", ""),
        PipelineStepResult("B", ["b"], 1, "", "ng"),
    ]
    with patch("reports.run_daily_pipeline.ROOT", tmp_path):
        with patch("reports.run_daily_pipeline.date") as mock_date:
            mock_date.today.return_value = date(2026, 4, 25)
            with patch("reports.run_daily_pipeline.run_pipeline", return_value=results):
                code = main(["--no-slack"])
    assert code == 1
    assert "統合レポート保存" in capsys.readouterr().out
