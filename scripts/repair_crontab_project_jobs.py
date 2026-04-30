#!/usr/bin/env python3
"""
壊れた crontab 行（重複パス・python3 乱れ等）を、このリポジトリ用の正しいジョブ行に差し替える。
sed で「海外輸出ボット && python3」を触らないこと（パス部分に誤マッチする）。

- 在庫管理: 毎時0分（CLAUDE ルール13）
- 注文監視: 毎時5分（在庫ジョブと起動をずらして負荷分散。通知は最大約1時間遅れ）
- 出品目標: 月火木金日10:00→70品（fill_daily 引数なし）、水土10:00→60品（fill60）
- python3 -u: cron の inventory.log / orders.log へ即時フラッシュ

使い方: python3 scripts/repair_crontab_project_jobs.py
        python3 scripts/repair_crontab_project_jobs.py --dry-run
        python3 scripts/repair_crontab_project_jobs.py --write-file=logs/crontab.new.txt
        # 手動適用: crontab logs/crontab.new.txt
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _root() -> str:
    return str(Path(__file__).resolve().parent.parent)


def _canonical_jobs(root: str) -> dict[str, str]:
    """キーは crontab 行の識別子（ログに含まれる一意の断片）"""
    cd = root
    py = "/usr/bin/python3"
    sh_fill = os.path.join(root, "scripts", "fill_daily_until_done.sh")
    sh60 = os.path.join(root, "scripts", "fill60_until_done.sh")
    return {
        "daily_report.py": f"0 8 * * * cd {cd} && {py} daily_report.py >> logs/daily_report.log 2>&1",
        "inventory_manager.py": f"0 * * * * cd {cd} && {py} -u inventory_manager.py >> logs/inventory.log 2>&1",
        "order_monitor.py": f"5 * * * * cd {cd} && {py} -u order_monitor.py >> logs/orders.log 2>&1",
        "fill_daily_70": (
            f"0 10 * * 1,2,4,5,0 cd {cd} && /bin/bash {sh_fill} >> logs/fill_daily_cron.log 2>&1"
        ),
        "fill_daily_60": (
            f"0 10 * * 3,6 cd {cd} && /bin/bash {sh60} >> logs/fill_daily_cron.log 2>&1"
        ),
        "auto_lister_20260404": f"0 21 4 4 * cd {cd} && {py} auto_lister.py >> logs/auto_lister_20260404.log 2>&1",
    }


def _line_targets_job(line: str, key: str) -> bool:
    if line.strip().startswith("#"):
        return False
    if key == "auto_lister_20260404":
        return "auto_lister.py" in line and "20260404" in line
    if key == "fill_daily_70":
        return "fill_daily_until_done.sh" in line
    if key == "fill_daily_60":
        return "fill60_until_done.sh" in line
    return key in line


def _build_new_crontab_lines(root: str) -> list[str]:
    canon = _canonical_jobs(root)
    keys_order = [
        "daily_report.py",
        "inventory_manager.py",
        "order_monitor.py",
        "fill_daily_70",
        "fill_daily_60",
        "auto_lister_20260404",
    ]

    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if r.returncode != 0 and not (r.stdout or "").strip():
        raise SystemExit("crontab が空です。")
    if r.returncode != 0:
        raise SystemExit(f"crontab -l 失敗: {r.stderr}")

    lines = r.stdout.rstrip("\n").split("\n")
    out: list[str] = []
    replaced: set[str] = set()

    for line in lines:
        # 旧・直列シェル（リポジトリから削除済み）。残ると毎時0分に失敗するだけ。
        s = line.strip()
        if s and not s.startswith("#") and "cron_hourly_zero.sh" in line:
            print("削除: cron_hourly_zero.sh 行（廃止）", file=sys.stderr)
            continue
        skip = False
        for key in keys_order:
            if _line_targets_job(line, key):
                if key in replaced:
                    print(f"削除（重複）: {key}", file=sys.stderr)
                    skip = True
                    break
                if line.strip() == canon[key]:
                    out.append(line)
                else:
                    out.append(canon[key])
                    print(f"置換: {key}", file=sys.stderr)
                replaced.add(key)
                skip = True
                break
        if not skip:
            out.append(line)

    for key in keys_order:
        if key not in replaced:
            out.append(canon[key])
            print(f"追加: {key}", file=sys.stderr)

    return out


def repair_crontab(dry_run: bool, write_file: str | None) -> int:
    root = _root()
    try:
        out = _build_new_crontab_lines(root)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 1

    new_body = "\n".join(out) + "\n"
    if dry_run:
        print(new_body)
        return 0

    if write_file:
        wp = write_file if os.path.isabs(write_file) else os.path.join(root, write_file)
        d = os.path.dirname(wp)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(wp, "w", encoding="utf-8") as f:
            f.write(new_body)
        print(f"書き出し: {wp} → 手動適用: crontab {wp}", file=sys.stderr)
        return 0

    fd, name = tempfile.mkstemp(suffix=".crontab", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_body)
        subprocess.run(["crontab", name], check=True)
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass

    print(f"crontab 修復完了（ROOT={root}）。", file=sys.stderr)
    return 0


def main() -> int:
    dry = "--dry-run" in sys.argv
    write_file: str | None = None
    for a in sys.argv:
        if a.startswith("--write-file="):
            write_file = a.split("=", 1)[1].strip()
            break
    return repair_crontab(dry_run=dry, write_file=write_file)


if __name__ == "__main__":
    raise SystemExit(main())
