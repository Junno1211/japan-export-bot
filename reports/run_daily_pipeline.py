#!/usr/bin/env python3
"""Phase 1 の日次レポートパイプラインを実行する。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT_STEPS: tuple[tuple[str, str], ...] = (
    ("部署別売上", "generate_dept_report.py"),
    ("Intelligence", "generate_intelligence_report.py"),
    ("Market Signals", "generate_market_signals.py"),
    ("Capital Allocation", "generate_allocation_report.py"),
)


@dataclass(frozen=True)
class PipelineStepResult:
    name: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def default_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)


def run_step(name: str, script_name: str, *, runner: Runner = default_runner) -> PipelineStepResult:
    cmd = [sys.executable, str(ROOT / "reports" / script_name)]
    try:
        proc = runner(cmd)
        return PipelineStepResult(name, list(cmd), int(proc.returncode), proc.stdout or "", proc.stderr or "")
    except Exception as e:  # noqa: BLE001 - 1ステップ失敗で全体を止めない
        return PipelineStepResult(name, list(cmd), 1, "", str(e))


def run_pipeline(*, runner: Runner = default_runner) -> list[PipelineStepResult]:
    return [run_step(name, script, runner=runner) for name, script in REPORT_STEPS]


def format_daily_report(results: list[PipelineStepResult], *, today: date) -> str:
    lines = [
        f"# Daily Phase 1 Pipeline - {today.isoformat()}",
        "",
        "| レポート | 状態 | 終了コード |",
        "|---|---|---:|",
    ]
    for result in results:
        status = "成功" if result.ok else "失敗"
        lines.append(f"| {result.name} | {status} | {result.returncode} |")

    lines.extend(["", "## 詳細", ""])
    for result in results:
        lines.append(f"### {result.name}")
        lines.append("")
        lines.append(f"- 状態: {'成功' if result.ok else '失敗'}")
        lines.append(f"- コマンド: `{' '.join(result.command)}`")
        if result.stdout.strip():
            lines.extend(["", "```text", result.stdout.strip()[-3000:], "```"])
        if result.stderr.strip():
            lines.extend(["", "```text", result.stderr.strip()[-3000:], "```"])
        lines.append("")
    return "\n".join(lines)


def save_daily_report(body: str, *, today: date) -> Path:
    out = ROOT / "reports" / "output" / f"daily_pipeline_{today.isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    return out


def load_slack_webhook_url() -> str | None:
    try:
        from config import SLACK_WEBHOOK_URL
    except Exception:
        return None
    value = (SLACK_WEBHOOK_URL or "").strip()
    return value or None


def build_slack_message(results: list[PipelineStepResult], report_path: Path) -> str:
    ok = sum(1 for r in results if r.ok)
    ng = len(results) - ok
    lines = [f"Phase 1 daily pipeline: 成功 {ok} / 失敗 {ng}", f"レポート: {report_path}"]
    for r in results:
        lines.append(f"- {r.name}: {'成功' if r.ok else '失敗しました'}")
    return "\n".join(lines)


def send_slack_message(webhook_url: str, text: str) -> bool:
    payload = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= int(resp.status) < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 1 の日次レポートを順次生成する")
    parser.add_argument("--no-slack", action="store_true", help="Slack 通知を送らない")
    args = parser.parse_args(argv)

    today = date.today()
    results = run_pipeline()
    body = format_daily_report(results, today=today)
    path = save_daily_report(body, today=today)
    print(body)
    print(f"統合レポート保存: {path.relative_to(ROOT)}")

    if not args.no_slack:
        webhook = load_slack_webhook_url()
        if webhook:
            sent = send_slack_message(webhook, build_slack_message(results, path))
            print(f"Slack通知: {'送信済み' if sent else '失敗'}")
        else:
            print("Slack通知: webhook 未設定のためスキップ")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
