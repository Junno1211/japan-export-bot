"""
listing_metrics.py — 1日あたりの出品実績をローカルに蓄積（JST）
auto_lister 各実行の成功/失敗件数を記録し、日別合計も更新する。
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from logging import getLogger
from typing import Dict, Optional, Tuple

_logger = getLogger(__name__)

JST = timezone(timedelta(hours=9))


def _logs_dir() -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    d = os.path.join(base, "logs")
    os.makedirs(d, exist_ok=True)
    return d


def _write_listing_stats_md(data: dict, now: datetime) -> None:
    """logs/LISTING_STATS.md に月別・直近日別を書く（人間が cat / Obsidian で見やすい）。"""
    months: dict = defaultdict(lambda: {"success": 0, "fail": 0, "days": 0})
    for day_key, row in data.items():
        if not isinstance(row, dict) or len(day_key) < 7:
            continue
        ym = day_key[:7]
        months[ym]["success"] += int(row.get("success", 0))
        months[ym]["fail"] += int(row.get("fail", 0))
        months[ym]["days"] += 1

    cutoff_day = (now.date() - timedelta(days=31)).isoformat()
    recent = sorted((k for k in data.keys() if k >= cutoff_day), reverse=True)

    lines = [
        "# 出品記録スナップショット（JST）",
        "",
        f"最終更新: {now.strftime('%Y-%m-%d %H:%M:%S')} JST",
        "",
        "`daily_listing_totals.json` から自動生成。",
        "**`deploy.sh` は本ファイルと JSON を VPS から上書きしない**（サーバの記録が消えない）。",
        "",
        "## 月別（success / fail / 日数）",
        "",
        "| 月 | success | fail | 日数 |",
        "|----|---------|------|------|",
    ]
    for ym in sorted(months.keys()):
        m = months[ym]
        lines.append(f"| {ym} | {m['success']} | {m['fail']} | {m['days']} |")
    lines.extend(
        [
            "",
            "## 日別（直近 31 日）",
            "",
            "| 日 (JST) | success | fail | sessions |",
            "|----------|---------|------|----------|",
        ]
    )
    for day_key in recent:
        row = data.get(day_key) or {}
        lines.append(
            f"| {day_key} | {row.get('success', 0)} | {row.get('fail', 0)} | "
            f"{row.get('sessions', 0)} |"
        )
    lines.append("")

    out = os.path.join(_logs_dir(), "LISTING_STATS.md")
    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as e:
        _logger.warning("LISTING_STATS.md 書き込み失敗: %s", e)


def record_listing_session(
    success: int,
    fail: int,
    by_department: Optional[Dict[str, int]] = None,
) -> None:
    """この auto_lister 実行の成功/失敗を JST 日付で記録する。

    by_department: keywords.json の「department」名ごとの成功件数（省略可・後方互換）。
    """
    now = datetime.now(JST)
    day = now.strftime("%Y-%m-%d")
    t = now.strftime("%H:%M:%S")
    log_dir = _logs_dir()

    tsv = os.path.join(log_dir, "daily_listing_sessions.tsv")
    write_header = not os.path.exists(tsv) or os.path.getsize(tsv) == 0
    with open(tsv, "a", encoding="utf-8") as f:
        if write_header:
            f.write("date_jst\ttime_jst\tsuccess\tfail\n")
        f.write(f"{day}\t{t}\t{success}\t{fail}\n")

    totals_path = os.path.join(log_dir, "daily_listing_totals.json")
    data: dict = {}
    if os.path.exists(totals_path):
        try:
            with open(totals_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}

    if day not in data:
        data[day] = {"success": 0, "fail": 0, "sessions": 0}
    data[day]["success"] = int(data[day].get("success", 0)) + int(success)
    data[day]["fail"] = int(data[day].get("fail", 0)) + int(fail)
    data[day]["sessions"] = int(data[day].get("sessions", 0)) + 1
    data[day]["last_time_jst"] = t

    if by_department:
        bd = data[day].setdefault("by_department", {})
        for k, v in by_department.items():
            label = (k or "未分類").strip() or "未分類"
            bd[label] = int(bd.get(label, 0)) + int(v)

    # 古い日付を大量に残さない（直近 120 日）
    cutoff = (now.date() - timedelta(days=120)).isoformat()
    data = {k: v for k, v in data.items() if k >= cutoff}

    with open(totals_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    try:
        _write_listing_stats_md(data, now)
    except Exception as e:
        _logger.warning("LISTING_STATS.md 更新失敗: %s", e)


def load_daily_totals() -> dict:
    """daily_listing_totals.json を読む（無ければ {}）。"""
    totals_path = os.path.join(_logs_dir(), "daily_listing_totals.json")
    if not os.path.exists(totals_path):
        return {}
    try:
        with open(totals_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _mirror_to_obsidian_vault(body: str, day: str) -> Optional[str]:
    """knowledge_vault/日報/出品_YYYY-MM-DD.md に同じ内容を書く（設定で無効可）。"""
    try:
        from config import OBSIDIAN_MIRROR, OBSIDIAN_VAULT_PATH
    except ImportError:
        return None
    if not OBSIDIAN_MIRROR:
        return None
    root = OBSIDIAN_VAULT_PATH
    if not root:
        return None
    sub = os.path.join(root, "日報")
    try:
        os.makedirs(sub, exist_ok=True)
        out = os.path.join(sub, f"出品_{day}.md")
        with open(out, "w", encoding="utf-8") as f:
            f.write(body)
        return out
    except OSError as e:
        _logger.warning("Obsidian Vault への日報ミラー失敗: %s", e)
        return None


def write_daily_report_md(day: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """JST の日付ごとの出品日報を Markdown で logs/daily_report_YYYY-MM-DD.md に書く。

    day: "YYYY-MM-DD"。省略時は今日 JST。
    戻り値: (logs 側パス, Obsidian ミラー先パス or None)
    """
    now = datetime.now(JST)
    if day is None:
        day = now.strftime("%Y-%m-%d")
    data = load_daily_totals()
    row = data.get(day) or {}

    success = int(row.get("success", 0))
    fail = int(row.get("fail", 0))
    sessions = int(row.get("sessions", 0))
    by_dept = row.get("by_department") or {}
    last_t = row.get("last_time_jst", "")

    lines = [
        f"# 出品日報 {day} (JST)",
        "",
        "## 本日の出品（auto_lister・eBay 成功ベース）",
        "",
        f"- **成功合計**: {success} 件",
        f"- **失敗合計**: {fail} 件",
        f"- **実行セッション数**: {sessions}",
    ]
    if last_t:
        lines.append(f"- **最終記録時刻 (JST)**: {last_t}")
    lines.extend(["", "## 分野別（sourcing の keywords「department」）", ""])

    if by_dept:
        lines.append("| 分野 | 件数 |")
        lines.append("|------|------|")
        for name in sorted(by_dept.keys(), key=lambda x: (-int(by_dept[x]), x)):
            lines.append(f"| {name} | {by_dept[name]} |")
        lines.append("")
        dept_sum = sum(int(v) for v in by_dept.values())
        if dept_sum != success and success > 0:
            lines.append(
                f"*分野別の合計 {dept_sum} 件は、成功合計 {success} 件と一致しません"
                "（古いデータや未記録セッションが混ざっている可能性があります）。*"
            )
            lines.append("")
    else:
        if success > 0:
            lines.append(
                "*この日の分野別集計は未記録です（listing_metrics 拡張前のデータ、"
                "または記録エラーの可能性があります）。*"
            )
        else:
            lines.append("*（この日の出品記録はありません）*")
        lines.append("")

    lines.append("")
    lines.append(
        "---\n*生成: `listing_metrics.write_daily_report_md` / "
        "`generate_daily_listing_report.py`*"
    )

    body = "\n".join(lines) + "\n"
    out_path = os.path.join(_logs_dir(), f"daily_report_{day}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)

    obs_path = _mirror_to_obsidian_vault(body, day)
    if obs_path:
        _logger.info("Obsidian 日報を更新: %s", obs_path)
    try:
        _write_listing_stats_md(data, now)
    except Exception as e:
        _logger.warning("LISTING_STATS.md 同期失敗: %s", e)
    return out_path, obs_path
